"""TypedDict discovery and structural record-transform materialization."""

import ast
from functools import singledispatch
from typing import assert_never

from returns.result import Failure, safe

from typeforge.compiler import evaluator as record_evaluator
from typeforge.compiler._markers import (
    AllMarker,
    AnyMarker,
    AssignableMarker,
    CaseMarker,
    DefaultMarker,
    DropMarker,
    EqualMarker,
    FieldMarker,
    KeyMarker,
    MapFieldsMarker,
    MapMarker,
    MarkerNormalizationError,
    NormalizedMarker,
    NotMarker,
    OptionalFieldMarker,
    ReadonlyFieldMarker,
    ValueMarker,
    normalize_marker,
)
from typeforge.compiler._pipeline_adaptation import (
    schema_inner_expression,
    substitute_type,
)
from typeforge.compiler._pipeline_models import (
    AdaptationError,
    DerivedRecord,
    EvaluatorAdaptationError,
    RecordMaterialization,
)
from typeforge.compiler._pipeline_utils import merge_imports
from typeforge.compiler._type_tree import rewrite_type
from typeforge.compiler.emitter import emit_stub_module
from typeforge.compiler.lowering import (
    ClassDeclaration,
    ClassField,
    Declaration,
    FunctionDeclaration,
    Import,
    OverloadDeclaration,
    Parameter,
    StubModule,
    TypeAliasDeclaration,
    TypeApplication,
    TypeExpression,
    TypeName,
    UnionExpression,
    VariableDeclaration,
)
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    SourceModule,
    StarredTypeExpression,
    UnionTypeExpression,
)
from typeforge.compiler.model import (
    TypeAliasDeclaration as SourceTypeAlias,
)
from typeforge.compiler.model import (
    TypedDictDeclaration as SourceTypedDict,
)
from typeforge.compiler.model import (
    TypeExpression as SourceTypeExpression,
)
from typeforge.compiler.records import (
    NamedType,
    NeverType,
    StaticType,
    TypedDictShape,
    UnionType,
)
from typeforge.compiler.records import (
    TypedDictField as StaticTypedDictField,
)
from typeforge.utils.error_handling import ok


@safe(exceptions=(AdaptationError,))
def materialize_record_transforms(
    module: SourceModule, stub: StubModule
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
    stub_functions = {
        declaration.name: declaration
        for declaration in stub.declarations
        if isinstance(declaration, FunctionDeclaration)
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
                stub_functions[name], controller, item.input_name, item.shape.name
            )
            for item in derived
            if item.alias == alias_name and item.shape.name is not None
        )
        if specialized:
            fallback = FunctionDeclaration(
                name=name,
                parameters=stub_functions[name].parameters,
                return_type=TypeName("object"),
                type_parameters=stub_functions[name].type_parameters,
                is_async=stub_functions[name].is_async,
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


def apply_record_materialization(
    module: StubModule, materialization: RecordMaterialization
) -> StubModule:
    replacements = dict(materialization.replacements)
    declarations = tuple(
        replace_record_aliases_in_declaration(
            replacements.get(declaration.name, declaration)
            if isinstance(declaration, FunctionDeclaration)
            else declaration,
            materialization.derived,
        )
        for declaration in module.declarations
    )
    imports = merge_imports((*module.imports, *materialization.imports))
    return StubModule(module.name, declarations, imports)


def replace_record_aliases_in_declaration(
    declaration: Declaration,
    derived: tuple[DerivedRecord, ...],
) -> Declaration:
    match declaration:
        case FunctionDeclaration():
            return replace_record_aliases_in_function(declaration, derived)
        case OverloadDeclaration():
            return replace_record_aliases_in_overload(declaration, derived)
        case TypeAliasDeclaration(name, value, type_parameters):
            return TypeAliasDeclaration(
                name,
                replace_record_aliases(value, derived),
                type_parameters,
            )
        case VariableDeclaration(name, annotation):
            return VariableDeclaration(
                name,
                replace_record_aliases(annotation, derived),
            )
        case ClassDeclaration(
            name, bases, fields, methods, type_parameters, keywords, decorators
        ):
            return ClassDeclaration(
                name,
                tuple(replace_record_aliases(base, derived) for base in bases),
                tuple(
                    ClassField(
                        field.name,
                        replace_record_aliases(field.annotation, derived),
                        field.default,
                    )
                    for field in fields
                ),
                tuple(
                    replace_record_aliases_in_function(method, derived)
                    if isinstance(method, FunctionDeclaration)
                    else replace_record_aliases_in_overload(method, derived)
                    for method in methods
                ),
                type_parameters,
                keywords,
                decorators,
            )
        case _ as unreachable:
            assert_never(unreachable)


def typed_dict_declaration(shape: TypedDictShape) -> ClassDeclaration:
    return ClassDeclaration(
        name=shape.name or "AnonymousTypedDict",
        bases=(TypeName("tf_typing.TypedDict"),),
        fields=tuple(
            ClassField(field.name, _typed_dict_field_type(field))
            for field in shape.fields
        ),
        methods=(),
    )


def _typed_dict_field_type(field: StaticTypedDictField) -> TypeExpression:
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


def _static_type_expression(value: StaticType) -> TypeExpression:
    match value:
        case NamedType(name):
            return TypeName(name)
        case NeverType():
            return TypeName("tf_typing.Never")
        case UnionType(members):
            return UnionExpression(
                tuple(_static_type_expression(member) for member in members)
            )
        case TypedDictShape(name):
            return TypeName(name or "object")
        case _ as unreachable:
            assert_never(unreachable)


def render_typed_dict(shape: TypedDictShape) -> str:
    """Render one TypedDict declaration for overlay consumers."""
    rendered = emit_stub_module(StubModule("", (typed_dict_declaration(shape),)))
    if isinstance(rendered, Failure):
        raise ValueError(rendered.failure())
    return rendered.unwrap().rstrip()


def replace_record_aliases_in_function(
    declaration: FunctionDeclaration,
    derived: tuple[DerivedRecord, ...],
) -> FunctionDeclaration:
    return FunctionDeclaration(
        declaration.name,
        tuple(
            Parameter(
                parameter.name,
                replace_record_aliases(parameter.annotation, derived),
                parameter.kind,
                parameter.default,
            )
            for parameter in declaration.parameters
        ),
        replace_record_aliases(declaration.return_type, derived),
        declaration.type_parameters,
        declaration.is_async,
        declaration.decorators,
    )


def replace_record_aliases_in_overload(
    declaration: OverloadDeclaration,
    derived: tuple[DerivedRecord, ...],
) -> OverloadDeclaration:
    return OverloadDeclaration(
        tuple(
            replace_record_aliases_in_function(signature, derived)
            for signature in declaration.signatures
        ),
        replace_record_aliases_in_function(declaration.fallback, derived),
        declaration.decorator,
    )


def replace_record_aliases(
    expression: TypeExpression,
    derived: tuple[DerivedRecord, ...],
) -> TypeExpression:
    replacements = {
        (item.alias, item.input_name): TypeName(item.shape.name or "object")
        for item in derived
    }

    def replace(current: TypeExpression) -> TypeExpression | None:
        match current:
            case TypeApplication(TypeName(alias), (TypeName(input_name),)):
                return replacements.get((alias, input_name))
            case _:
                return None

    return rewrite_type(expression, replace)


def build_record_shapes(
    declarations: tuple[SourceTypedDict, ...],
) -> tuple[TypedDictShape, ...]:
    shapes: list[TypedDictShape] = []
    by_name: dict[tuple[str, ...], TypedDictShape] = {}
    for declaration in declarations:
        inherited = tuple(
            field
            for base in declaration.bases
            for field in by_name.get(base, TypedDictShape(None, ())).fields
        )
        own_fields = tuple(
            StaticTypedDictField(
                field.name,
                NamedType(field.annotation.source),
                field.required,
                field.readonly,
            )
            for field in declaration.fields
        )
        shape = TypedDictShape(declaration.name, (*inherited, *own_fields))
        shapes.append(shape)
        by_name[declaration.qualified_name] = shape
    return tuple(shapes)


@safe(exceptions=(AdaptationError,))
def derive_record_shapes(
    aliases: tuple[SourceTypeAlias, ...], source_shapes: tuple[TypedDictShape, ...]
) -> tuple[DerivedRecord, ...]:
    return _derive_record_shapes(aliases, source_shapes)


def _derive_record_shapes(
    aliases: tuple[SourceTypeAlias, ...], source_shapes: tuple[TypedDictShape, ...]
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
            raise AdaptationError(
                alias.name,
                alias.value.source,
                "MapFields aliases require exactly one type parameter",
            )
        parameter = alias.type_parameters[0].name
        for source_shape in source_shapes:
            output_name = f"{alias.name}_{source_shape.name}"
            try:
                evaluator_expression = adapt_evaluator_expression(
                    value, ((parameter, source_shape),), output_name
                )
            except EvaluatorAdaptationError as error:
                raise AdaptationError(
                    alias.name, alias.value.source, error.message
                ) from error
            if not isinstance(evaluator_expression, record_evaluator.MapFields):
                raise AdaptationError(
                    alias.name,
                    alias.value.source,
                    "alias must evaluate to MapFields",
                )
            try:
                evaluated = ok(record_evaluator.evaluate(evaluator_expression))
            except record_evaluator.EvaluationError as error:
                raise AdaptationError(
                    alias.name,
                    alias.value.source,
                    error.message,
                ) from error
            if not isinstance(evaluated, TypedDictShape):
                raise AdaptationError(
                    alias.name,
                    alias.value.source,
                    "MapFields must evaluate to a TypedDictShape",
                )
            derived.append(
                DerivedRecord(
                    alias.name,
                    source_shape.name or "",
                    evaluated,
                )
            )
    return tuple(derived)


@singledispatch
def adapt_evaluator_expression(
    expression: SourceTypeExpression,
    environment: tuple[tuple[str, StaticType], ...],
    output_name: str | None = None,
) -> record_evaluator.Expression:
    raise EvaluatorAdaptationError(
        f"unsupported record expression {type(expression).__name__}"
    )


@adapt_evaluator_expression.register
def _(
    expression: NameTypeExpression,
    environment: tuple[tuple[str, StaticType], ...],
    output_name: str | None = None,
) -> record_evaluator.Expression:
    bound = dict(environment).get(expression.source)
    return bound if bound is not None else NamedType(expression.source)


@adapt_evaluator_expression.register
def _(
    expression: RawTypeExpression | UnionTypeExpression | StarredTypeExpression,
    environment: tuple[tuple[str, StaticType], ...],
    output_name: str | None = None,
) -> record_evaluator.Expression:
    return NamedType(expression.source)


@adapt_evaluator_expression.register
def _(
    expression: AppliedTypeExpression,
    environment: tuple[tuple[str, StaticType], ...],
    output_name: str | None = None,
) -> record_evaluator.Expression:
    return adapt_field_name_literal(expression) or NamedType(expression.source)


@adapt_evaluator_expression.register
def _(
    expression: MarkerTypeExpression,
    environment: tuple[tuple[str, StaticType], ...],
    output_name: str | None = None,
) -> record_evaluator.Expression:
    marker = _normalize_evaluator_marker(expression)

    def adapt(item: SourceTypeExpression) -> record_evaluator.Expression:
        return adapt_evaluator_expression(item, environment)

    match marker:
        case KeyMarker():
            return record_evaluator.Key()
        case ValueMarker():
            return record_evaluator.Value()
        case DropMarker():
            return record_evaluator.Drop()
        case FieldMarker(key=key, value=value):
            return record_evaluator.Field(adapt(key), adapt(value))
        case OptionalFieldMarker(key=key, value=value):
            return record_evaluator.OptionalField(adapt(key), adapt(value))
        case ReadonlyFieldMarker(key=key, value=value):
            return record_evaluator.ReadonlyField(adapt(key), adapt(value))
        case MapFieldsMarker(record=record, transform=transform):
            return record_evaluator.MapFields(
                adapt(record), adapt(transform), output_name
            )
        case MapMarker(subject=subject, entries=entries):
            cases = tuple(
                record_evaluator.Case(adapt(entry.test), adapt(entry.output))
                for entry in entries
                if isinstance(entry, CaseMarker)
            )
            default = next(
                (
                    adapt(entry.output)
                    for entry in entries
                    if isinstance(entry, DefaultMarker)
                ),
                None,
            )
            return (
                record_evaluator.Map(adapt(subject), cases)
                if default is None
                else record_evaluator.Map(adapt(subject), cases, default)
            )
        case EqualMarker(left=left, right=right):
            return record_evaluator.Equal(adapt(left), adapt(right))
        case AssignableMarker(left=left, right=right):
            return record_evaluator.Assignable(adapt(left), adapt(right))
        case AllMarker(items=items):
            return record_evaluator.All(tuple(adapt(item) for item in items))
        case AnyMarker(items=items):
            return record_evaluator.Any(tuple(adapt(item) for item in items))
        case NotMarker(item=item):
            return record_evaluator.Not(adapt(item))
        case _:
            raise EvaluatorAdaptationError(
                f"unsupported record expression "
                f"{type(marker).__name__.removesuffix('Marker')}"
            )


def adapt_evaluator_expressions(
    expressions: tuple[SourceTypeExpression, ...],
    environment: tuple[tuple[str, StaticType], ...],
) -> tuple[record_evaluator.Expression, ...]:
    return tuple(
        adapt_evaluator_expression(expression, environment)
        for expression in expressions
    )


def _normalize_evaluator_marker(
    expression: MarkerTypeExpression,
) -> NormalizedMarker:
    try:
        return normalize_marker(expression)
    except MarkerNormalizationError as error:
        raise EvaluatorAdaptationError(error.message) from error


def adapt_field_name_literal(
    expression: AppliedTypeExpression,
) -> record_evaluator.FieldName | None:
    if not isinstance(expression.constructor, NameTypeExpression):
        return None
    if expression.constructor.source != "Literal" or len(expression.arguments) != 1:
        return None
    argument = expression.arguments[0]
    if not isinstance(argument, RawTypeExpression):
        return None
    try:
        value = ast.literal_eval(argument.source)
    except SyntaxError, ValueError:
        return None
    return record_evaluator.FieldName(value) if isinstance(value, str) else None


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
) -> FunctionDeclaration:
    concrete_input = TypeName(input_name)
    return FunctionDeclaration(
        name=function.name,
        parameters=tuple(
            Parameter(
                parameter.name,
                substitute_type(parameter.annotation, controller, concrete_input),
                parameter.kind,
                parameter.default,
            )
            for parameter in function.parameters
        ),
        return_type=TypeName(output_name or "object"),
        type_parameters=tuple(
            parameter
            for parameter in function.type_parameters
            if parameter != controller
        ),
        is_async=function.is_async,
    )
