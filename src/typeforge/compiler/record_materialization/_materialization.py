"""TypedDict discovery and structural record-transform materialization."""

from dataclasses import replace
from typing import assert_never

from returns.result import Failure, safe

from typeforge.compiler.record_materialization._models import (
    DerivedRecord,
    RecordMaterialization,
    RecordMaterializationError,
)
from typeforge.compiler.semantic_adapter import (
    COMPILER_TYPE_SYSTEM,
    NamedType,
    NeverType,
    ParameterizedType,
    SemanticLoweringError,
    StaticType,
    UnionType,
    lower_semantic_expression,
)
from typeforge.compiler.source import (
    AppliedTypeExpression,
    MapFieldsMarker,
    MarkerNormalizationError,
    MarkerTypeExpression,
    NameTypeExpression,
    SourceModule,
    SourceTypeExpression,
    normalize_marker,
    schema_inner_expression,
)
from typeforge.compiler.source import (
    TypeAliasDeclaration as SourceTypeAlias,
)
from typeforge.compiler.source import (
    TypedDictDeclaration as SourceTypedDict,
)
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    ClassField,
    Declaration,
    FunctionDeclaration,
    Import,
    OverloadDeclaration,
    StubModule,
    StubTypeExpression,
    TypeAliasDeclaration,
    TypeApplication,
    TypeName,
    TypeRewriteObserver,
    UnionExpression,
    VariableDeclaration,
    rewrite_type,
    substitute_type,
)
from typeforge.semantics import (
    MapFieldsExpression,
    RecordFamily,
    RecordField,
    RecordShape,
    evaluate,
)


@safe(exceptions=(RecordMaterializationError,))
def materialize_record_transforms(
    module: SourceModule,
    stub: StubModule,
    on_rewrite: TypeRewriteObserver | None = None,
) -> RecordMaterialization:
    if not module.typed_dicts:
        return RecordMaterialization((), (), ())

    source_shapes = build_record_shapes(module.typed_dicts)
    derived = _derive_record_shapes(module.aliases, source_shapes)
    replacements: list[tuple[str, OverloadDeclaration]] = []
    source_functions = {
        function.name: function
        for function in module.functions
        if len(function.qualified_name) == 1
    }
    scoped_spans = {
        function.span
        for function in module.functions
        if len(function.qualified_name) > 1
    }
    scoped_functions = {
        id(origin.generated) for origin in stub.origins if origin.origin in scoped_spans
    }
    stub_functions = {
        declaration.name: declaration
        for declaration in stub.declarations
        if isinstance(declaration, FunctionDeclaration)
        and id(declaration) not in scoped_functions
    }
    for name, source_function in source_functions.items():
        if name not in stub_functions or source_function.returns is None:
            continue

        alias_reference = map_fields_alias_reference(
            source_function.returns, module.aliases
        )
        if alias_reference is None:
            continue

        alias_name, controller = alias_reference
        specialized = tuple(
            specialize_record_function(
                stub_functions[name],
                controller,
                item.input_name,
                item.shape.name,
                on_rewrite=on_rewrite,
            )
            for item in derived
            if item.alias == alias_name and item.shape.name is not None
        )
        if specialized:
            fallback = replace(
                stub_functions[name],
                return_type=TypeName("object"),
                decorators=(),
            )
            replacements.append(
                (
                    name,
                    OverloadDeclaration(
                        signatures=specialized,
                        fallback=fallback,
                        decorator="tf_typing.overload",
                    ),
                )
            )

    declarations = tuple(
        typed_dict_declaration(shape)
        for shape in (*source_shapes, *(item.shape for item in derived))
    )
    return RecordMaterialization(
        declarations=declarations,
        replacements=tuple(replacements),
        imports=(Import("typing", "tf_typing"),),
        derived=derived,
    )


def replace_record_aliases_in_declaration(
    declaration: Declaration,
    derived: tuple[DerivedRecord, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> Declaration:
    match declaration:
        case FunctionDeclaration():
            return replace_record_aliases_in_function(
                declaration, derived, on_rewrite=on_rewrite
            )
        case OverloadDeclaration():
            return replace_record_aliases_in_overload(
                declaration, derived, on_rewrite=on_rewrite
            )
        case TypeAliasDeclaration():
            return replace(
                declaration,
                value=replace_record_aliases(
                    declaration.value, derived, on_rewrite=on_rewrite
                ),
            )
        case VariableDeclaration():
            return replace(
                declaration,
                annotation=replace_record_aliases(
                    declaration.annotation, derived, on_rewrite=on_rewrite
                ),
            )
        case ClassDeclaration():
            return replace(
                declaration,
                bases=tuple(
                    replace_record_aliases(base, derived, on_rewrite=on_rewrite)
                    for base in declaration.bases
                ),
                fields=tuple(
                    replace(
                        field,
                        annotation=replace_record_aliases(
                            field.annotation, derived, on_rewrite=on_rewrite
                        ),
                    )
                    for field in declaration.fields
                ),
                methods=tuple(
                    replace_record_aliases_in_function(
                        method, derived, on_rewrite=on_rewrite
                    )
                    if isinstance(method, FunctionDeclaration)
                    else replace_record_aliases_in_overload(
                        method, derived, on_rewrite=on_rewrite
                    )
                    for method in declaration.methods
                ),
            )
        case _ as unreachable:
            assert_never(unreachable)


def typed_dict_declaration(shape: RecordShape[StaticType]) -> ClassDeclaration:
    if shape.family is not RecordFamily.TYPED_DICT:
        raise ValueError(f"cannot emit {shape.family.value} record as a TypedDict")

    return ClassDeclaration(
        name=shape.name or "AnonymousTypedDict",
        bases=(TypeName("tf_typing.TypedDict"),),
        fields=tuple(
            ClassField(field.name, _typed_dict_field_type(field))
            for field in shape.fields
        ),
        methods=(),
    )


def _typed_dict_field_type(field: RecordField[StaticType]) -> StubTypeExpression:
    annotation = _static_type_expression(field.value)
    if field.readonly:
        annotation = TypeApplication(
            TypeName("tf_typing.ReadOnly"),
            (annotation,),
        )

    if not field.required:
        annotation = TypeApplication(
            TypeName("tf_typing.NotRequired"),
            (annotation,),
        )

    return annotation


def _static_type_expression(value: StaticType) -> StubTypeExpression:
    match value:
        case NamedType(name):
            return TypeName(name)
        case NeverType():
            return TypeName("tf_typing.Never")
        case ParameterizedType(origin, arguments):
            return TypeApplication(
                _static_type_expression(origin),
                tuple(_static_type_expression(argument) for argument in arguments),
            )
        case UnionType(members):
            return UnionExpression(
                tuple(_static_type_expression(member) for member in members)
            )
        case RecordShape(name=name):
            return TypeName(name or "object")
        case _ as unreachable:
            assert_never(unreachable)


def replace_record_aliases_in_function(
    declaration: FunctionDeclaration,
    derived: tuple[DerivedRecord, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> FunctionDeclaration:
    return replace(
        declaration,
        parameters=tuple(
            replace(
                parameter,
                annotation=replace_record_aliases(
                    parameter.annotation, derived, on_rewrite=on_rewrite
                ),
            )
            for parameter in declaration.parameters
        ),
        return_type=replace_record_aliases(
            declaration.return_type, derived, on_rewrite=on_rewrite
        ),
    )


def replace_record_aliases_in_overload(
    declaration: OverloadDeclaration,
    derived: tuple[DerivedRecord, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> OverloadDeclaration:
    return replace(
        declaration,
        signatures=tuple(
            replace_record_aliases_in_function(
                signature, derived, on_rewrite=on_rewrite
            )
            for signature in declaration.signatures
        ),
        fallback=replace_record_aliases_in_function(
            declaration.fallback, derived, on_rewrite=on_rewrite
        ),
    )


def replace_record_aliases(
    expression: StubTypeExpression,
    derived: tuple[DerivedRecord, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    replacements = {
        (item.alias, item.input_name): TypeName(item.shape.name or "object")
        for item in derived
    }

    def replace_alias(current: StubTypeExpression) -> StubTypeExpression | None:
        match current:
            case TypeApplication(TypeName(alias), (TypeName(input_name),)):
                return replacements.get((alias, input_name))
            case _:
                return None

    return rewrite_type(expression, replace_alias, on_rewrite=on_rewrite)


def build_record_shapes(
    declarations: tuple[SourceTypedDict, ...],
) -> tuple[RecordShape[StaticType], ...]:
    shapes: list[RecordShape[StaticType]] = []
    by_name: dict[tuple[str, ...], RecordShape[StaticType]] = {}
    empty_shape = RecordShape[StaticType](
        family=RecordFamily.TYPED_DICT,
        name=None,
        fields=(),
    )
    for declaration in declarations:
        inherited = tuple(
            field
            for base in declaration.bases
            for field in by_name.get(base, empty_shape).fields
        )
        own_fields = tuple(
            RecordField[StaticType](
                name=field.name,
                value=NamedType(field.annotation.source),
                required=field.required,
                readonly=field.readonly,
            )
            for field in declaration.fields
        )
        shape = RecordShape[StaticType](
            family=RecordFamily.TYPED_DICT,
            name=declaration.name,
            fields=(*inherited, *own_fields),
        )
        shapes.append(shape)
        by_name[declaration.qualified_name] = shape

    return tuple(shapes)


@safe(exceptions=(RecordMaterializationError,))
def derive_record_shapes(
    aliases: tuple[SourceTypeAlias, ...],
    source_shapes: tuple[RecordShape[StaticType], ...],
) -> tuple[DerivedRecord, ...]:
    return _derive_record_shapes(aliases, source_shapes)


def _derive_record_shapes(
    aliases: tuple[SourceTypeAlias, ...],
    source_shapes: tuple[RecordShape[StaticType], ...],
) -> tuple[DerivedRecord, ...]:
    derived: list[DerivedRecord] = []
    for alias in aliases:
        value = schema_inner_expression(alias.value)
        if not isinstance(value, MarkerTypeExpression):
            continue

        try:
            marker = normalize_marker(value)
        except MarkerNormalizationError:
            continue

        if not isinstance(marker, MapFieldsMarker):
            continue

        if len(alias.type_parameters) != 1:
            raise RecordMaterializationError(
                alias.name,
                alias.value.source,
                "MapFields aliases require exactly one type parameter",
            )

        parameter = alias.type_parameters[0].name
        for source_shape in source_shapes:
            output_name = f"{alias.name}_{source_shape.name}"
            try:
                semantic_expression = lower_semantic_expression(
                    value, ((parameter, source_shape),), output_name
                )
            except SemanticLoweringError as error:
                raise RecordMaterializationError(
                    alias.name, alias.value.source, error.message
                ) from error

            if not isinstance(semantic_expression, MapFieldsExpression):
                raise RecordMaterializationError(
                    alias.name,
                    alias.value.source,
                    "alias must evaluate to MapFields",
                )

            evaluated_result = evaluate(semantic_expression, COMPILER_TYPE_SYSTEM)
            if isinstance(evaluated_result, Failure):
                raise RecordMaterializationError(
                    alias.name,
                    alias.value.source,
                    evaluated_result.failure().message,
                )

            evaluated = evaluated_result.unwrap()
            if not isinstance(evaluated, RecordShape):
                raise RecordMaterializationError(
                    alias.name,
                    alias.value.source,
                    "MapFields must evaluate to a record shape",
                )

            derived.append(
                DerivedRecord(
                    alias.name,
                    source_shape.name or "",
                    evaluated,
                )
            )

    return tuple(derived)


def map_fields_alias_reference(
    expression: SourceTypeExpression,
    aliases: tuple[SourceTypeAlias, ...],
) -> tuple[str, str] | None:
    if not isinstance(expression, AppliedTypeExpression):
        return None

    if not isinstance(expression.constructor, NameTypeExpression):
        return None

    if len(expression.arguments) != 1:
        return None

    argument = expression.arguments[0]
    if not isinstance(argument, NameTypeExpression):
        return None

    alias_name = expression.constructor.source
    if any(
        alias.name == alias_name and is_map_fields_alias(alias) for alias in aliases
    ):
        return alias_name, argument.source

    return None


def is_map_fields_alias(alias: SourceTypeAlias) -> bool:
    value = schema_inner_expression(alias.value)
    if not isinstance(value, MarkerTypeExpression):
        return False

    try:
        return isinstance(normalize_marker(value), MapFieldsMarker)
    except MarkerNormalizationError:
        return False


def specialize_record_function(
    function: FunctionDeclaration,
    controller: str,
    input_name: str,
    output_name: str | None,
    on_rewrite: TypeRewriteObserver | None = None,
) -> FunctionDeclaration:
    concrete_input = TypeName(input_name)
    return replace(
        function,
        parameters=tuple(
            replace(
                parameter,
                annotation=substitute_type(
                    parameter.annotation,
                    controller,
                    concrete_input,
                    on_rewrite=on_rewrite,
                ),
            )
            for parameter in function.parameters
        ),
        return_type=TypeName(output_name or "object"),
        type_parameters=tuple(
            parameter
            for parameter in function.type_parameters
            if parameter != controller
        ),
        decorators=(),
    )
