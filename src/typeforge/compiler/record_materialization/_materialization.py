"""TypedDict discovery and structural record-transform materialization."""

from dataclasses import replace

from returns.result import Failure, safe

from typeforge.compiler.record_materialization._models import (
    DerivedRecord,
    RecordMaterialization,
    RecordMaterializationError,
)
from typeforge.compiler.record_materialization._naming import available_record_name
from typeforge.compiler.semantic_adapter import (
    COMPILER_TYPE_SYSTEM,
    SemanticEnvironment,
    SemanticLoweringError,
    StaticType,
    lower_semantic_expression,
    static_type_expression,
)
from typeforge.compiler.source import (
    AppliedTypeExpression,
    NameTypeExpression,
    RecordTypeExpression,
    SourceModule,
    SourceTypeExpression,
    opaque_enriched_annotations,
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
    FunctionDeclaration,
    Import,
    OverloadDeclaration,
    StubModule,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeRewriteObserver,
    substitute_type,
    union_types,
)
from typeforge.semantics import (
    EvaluationValue,
    Expression,
    MapNoMatch,
    RecordExpression,
    RecordFamily,
    RecordField,
    RecordShape,
    RecordUnion,
    ResolvedType,
    evaluate,
)
from typeforge.utils.error_handling import safe_result


@safe_result(errors=(RecordMaterializationError,))
def materialize_record_transforms(
    module: SourceModule,
    stub: StubModule,
    on_rewrite: TypeRewriteObserver | None = None,
    *,
    environment: SemanticEnvironment = (),
) -> RecordMaterialization:
    if not module.typed_dicts:
        return RecordMaterialization((), (), ())

    source_shapes = build_record_shapes(
        module.typed_dicts, environment=environment
    ).unwrap()
    occupied = {
        *(item.name for item in module.identifiers),
        *(declaration.name for declaration in module.classes),
        *(function.name for function in module.functions),
    }
    derived = _derive_record_shapes(
        module.aliases, source_shapes, environment, occupied=occupied
    )
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

        alias_reference = record_alias_reference(
            source_function.returns, module.aliases
        )
        if alias_reference is None:
            continue

        alias_name, controller = alias_reference
        outputs: dict[str, list[StubTypeExpression]] = {}
        for item in derived:
            if item.alias == alias_name and item.shape.name is not None:
                outputs.setdefault(item.input_name, []).append(
                    TypeName(item.shape.name)
                )

        specialized = tuple(
            specialize_record_function(
                stub_functions[name],
                controller,
                input_name,
                union_types(tuple(members)),
                on_rewrite=on_rewrite,
            )
            for input_name, members in outputs.items()
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
        source_shapes=source_shapes,
    )


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
    annotation = static_type_expression(field.value, never_name="tf_typing.Never")
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


@safe(exceptions=(RecordMaterializationError,))
def build_record_shapes(
    declarations: tuple[SourceTypedDict, ...],
    *,
    environment: SemanticEnvironment = (),
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
                value=_record_field_type(
                    declaration.name, field.annotation, environment
                ),
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


def _record_field_type(
    declaration: str,
    annotation: SourceTypeExpression,
    environment: SemanticEnvironment,
) -> StaticType:
    try:
        expression = lower_semantic_expression(
            opaque_enriched_annotations(annotation), environment
        )
    except SemanticLoweringError as error:
        raise RecordMaterializationError(
            declaration, annotation.source, error.message
        ) from error

    value = _evaluate_record_expression(declaration, annotation, expression)
    if not isinstance(value, ResolvedType):
        raise RecordMaterializationError(
            declaration, annotation.source, "record fields must evaluate to types"
        )

    return value.value


def _evaluate_record_expression(
    declaration: str,
    authored: SourceTypeExpression,
    expression: Expression[StaticType],
) -> EvaluationValue[StaticType]:
    result = evaluate(expression, COMPILER_TYPE_SYSTEM)
    if isinstance(result, Failure):
        issue = result.failure()
        message = (
            "Map cannot transform a field: no case matched and no default was provided"
            if isinstance(issue, MapNoMatch)
            else issue.message
        )
        raise RecordMaterializationError(declaration, authored.source, message)

    return result.unwrap()


@safe(exceptions=(RecordMaterializationError,))
def evaluate_record_application(
    declaration: str,
    authored: SourceTypeExpression,
    expanded: SourceTypeExpression,
    *,
    environment: SemanticEnvironment,
) -> RecordShape[StaticType] | RecordUnion[StaticType]:
    """Evaluate a concrete application with its original complete argument."""
    try:
        expression = lower_semantic_expression(expanded, environment)
    except SemanticLoweringError as error:
        raise RecordMaterializationError(
            declaration, authored.source, error.message
        ) from error

    value = _evaluate_record_expression(declaration, authored, expression)
    if not isinstance(value, RecordShape | RecordUnion):
        raise RecordMaterializationError(
            declaration, authored.source, "Record must evaluate to complete records"
        )

    return value


@safe(exceptions=(RecordMaterializationError,))
def derive_record_shapes(
    aliases: tuple[SourceTypeAlias, ...],
    source_shapes: tuple[RecordShape[StaticType], ...],
    *,
    environment: SemanticEnvironment = (),
) -> tuple[DerivedRecord, ...]:
    return _derive_record_shapes(aliases, source_shapes, environment)


def _derive_record_shapes(
    aliases: tuple[SourceTypeAlias, ...],
    source_shapes: tuple[RecordShape[StaticType], ...],
    environment: SemanticEnvironment,
    *,
    occupied: set[str] | None = None,
) -> tuple[DerivedRecord, ...]:
    occupied = set() if occupied is None else set(occupied)
    occupied.update(alias.name for alias in aliases)
    occupied.update(shape.name for shape in source_shapes if shape.name is not None)
    occupied.update(
        f"{alias.name}_{shape.name}"
        for alias in aliases
        if is_record_alias(alias)
        for shape in source_shapes
    )
    derived: list[DerivedRecord] = []
    for alias in aliases:
        value = schema_inner_expression(alias.value)
        if not is_record_alias(alias):
            continue

        if len(alias.type_parameters) != 1:
            raise RecordMaterializationError(
                alias.name,
                alias.value.source,
                "record aliases require exactly one type parameter",
            )

        parameter = alias.type_parameters[0].name
        for source_shape in source_shapes:
            output_name = f"{alias.name}_{source_shape.name}"
            try:
                semantic_expression = lower_semantic_expression(
                    value,
                    (
                        *environment,
                        *((shape.name or "", shape) for shape in source_shapes),
                        (parameter, source_shape),
                    ),
                )
            except SemanticLoweringError as error:
                raise RecordMaterializationError(
                    alias.name, alias.value.source, error.message
                ) from error

            if not isinstance(semantic_expression, RecordExpression):
                raise RecordMaterializationError(
                    alias.name,
                    alias.value.source,
                    "alias must evaluate to Record",
                )

            evaluated = _evaluate_record_expression(
                alias.name, alias.value, semantic_expression
            )
            if not isinstance(evaluated, RecordShape | RecordUnion):
                raise RecordMaterializationError(
                    alias.name,
                    alias.value.source,
                    "Record must evaluate to a record shape",
                )

            members = (
                evaluated.members
                if isinstance(evaluated, RecordUnion)
                else (evaluated,)
            )
            for member in members:
                name = (
                    available_record_name(f"{output_name}_{member.name}", occupied)
                    if len(members) > 1
                    else output_name
                )
                occupied.add(name)
                derived.append(
                    DerivedRecord(
                        alias.name,
                        source_shape.name or "",
                        replace(member, name=name),
                        member.name,
                    )
                )

    return tuple(derived)


def record_alias_reference(
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
    if any(alias.name == alias_name and is_record_alias(alias) for alias in aliases):
        return alias_name, argument.source

    return None


def is_record_alias(alias: SourceTypeAlias) -> bool:
    return isinstance(schema_inner_expression(alias.value), RecordTypeExpression)


def specialize_record_function(
    function: FunctionDeclaration,
    controller: str,
    input_name: str,
    output_type: StubTypeExpression,
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
        return_type=output_type,
        type_parameters=tuple(
            parameter
            for parameter in function.type_parameters
            if parameter != controller
        ),
        decorators=(),
    )
