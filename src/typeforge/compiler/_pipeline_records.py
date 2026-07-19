"""TypedDict discovery and structural record-transform materialization."""

import ast
from functools import singledispatch
from typing import assert_never

from returns.result import safe

from typeforge.compiler import evaluator as record_evaluator
from typeforge.compiler._pipeline_core import schema_inner_expression, substitute_type
from typeforge.compiler._pipeline_models import (
    AdaptationError,
    DerivedRecord,
    EvaluatorAdaptationError,
    RecordMaterialization,
)
from typeforge.compiler._pipeline_utils import (
    merge_imports,
    render_typed_dict,
)
from typeforge.compiler.lowering import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    ClassDeclaration,
    ClassField,
    CollectType,
    Declaration,
    EachType,
    EqualPredicate,
    FieldType,
    FixedTuple,
    FunctionDeclaration,
    HomogeneousTuple,
    IfType,
    Import,
    LiteralType,
    MapCase,
    MapFieldsType,
    MapType,
    MapValueType,
    NotPredicate,
    OverloadDeclaration,
    Parameter,
    Predicate,
    RuntimeInputType,
    SchemaType,
    StubModule,
    TypeAliasDeclaration,
    TypeApplication,
    TypeExpression,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
)
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerKind,
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
    StaticType,
    TypedDictShape,
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
        render_typed_dict(shape)
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
    if (
        isinstance(expression, TypeApplication)
        and isinstance(expression.constructor, TypeName)
        and len(expression.arguments) == 1
        and isinstance(expression.arguments[0], TypeName)
    ):
        alias = expression.constructor.name
        input_name = expression.arguments[0].name
        match = next(
            (
                item
                for item in derived
                if item.alias == alias and item.input_name == input_name
            ),
            None,
        )
        if match is not None:
            return TypeName(match.shape.name or "object")
    match expression:
        case TypeApplication(constructor, arguments):
            return TypeApplication(
                replace_record_aliases(constructor, derived),
                tuple(
                    replace_record_aliases(argument, derived) for argument in arguments
                ),
            )
        case FixedTuple(items):
            return FixedTuple(
                tuple(replace_record_aliases(item, derived) for item in items)
            )
        case HomogeneousTuple(item):
            return HomogeneousTuple(replace_record_aliases(item, derived))
        case EachType(item):
            return EachType(replace_record_aliases(item, derived))
        case CollectType(item):
            return CollectType(replace_record_aliases(item, derived))
        case UnpackedType(item):
            return UnpackedType(replace_record_aliases(item, derived))
        case UnionExpression(members):
            return UnionExpression(
                tuple(replace_record_aliases(member, derived) for member in members)
            )
        case IfType(condition, when_true, when_false):
            return IfType(
                _replace_record_aliases_in_predicate(condition, derived),
                replace_record_aliases(when_true, derived),
                replace_record_aliases(when_false, derived),
            )
        case MapType(subject, cases, default):
            return MapType(
                replace_record_aliases(subject, derived),
                tuple(
                    MapCase(
                        replace_record_aliases(case.input_type, derived),
                        replace_record_aliases(case.output_type, derived),
                    )
                    for case in cases
                ),
                replace_record_aliases(default, derived),
            )
        case FieldType(name, value, required, readonly):
            return FieldType(
                replace_record_aliases(name, derived),
                replace_record_aliases(value, derived),
                required,
                readonly,
            )
        case MapFieldsType(record, transform):
            return MapFieldsType(
                replace_record_aliases(record, derived),
                replace_record_aliases(transform, derived),
            )
        case SchemaType(item):
            return SchemaType(replace_record_aliases(item, derived))
        case (
            TypeName()
            | TypeVariable()
            | LiteralType()
            | MapValueType()
            | RuntimeInputType()
        ):
            return expression
        case _ as unreachable:
            assert_never(unreachable)


def _replace_record_aliases_in_predicate(
    predicate: Predicate,
    derived: tuple[DerivedRecord, ...],
) -> Predicate:
    match predicate:
        case EqualPredicate(left, right):
            return EqualPredicate(
                replace_record_aliases(left, derived),
                replace_record_aliases(right, derived),
            )
        case AssignablePredicate(source, target):
            return AssignablePredicate(
                replace_record_aliases(source, derived),
                replace_record_aliases(target, derived),
            )
        case AllPredicate(predicates):
            return AllPredicate(
                tuple(
                    _replace_record_aliases_in_predicate(item, derived)
                    for item in predicates
                )
            )
        case AnyPredicate(predicates):
            return AnyPredicate(
                tuple(
                    _replace_record_aliases_in_predicate(item, derived)
                    for item in predicates
                )
            )
        case NotPredicate(item):
            return NotPredicate(_replace_record_aliases_in_predicate(item, derived))
        case _ as unreachable:
            assert_never(unreachable)


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
        if value.marker is not MarkerKind.MAP_FIELDS:
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
    marker = expression.marker
    if marker is MarkerKind.KEY:
        _require_evaluator_arity(expression, 0, "no")
        return record_evaluator.Key()
    if marker is MarkerKind.VALUE:
        _require_evaluator_arity(expression, 0, "no")
        return record_evaluator.Value()
    if marker is MarkerKind.DROP:
        _require_evaluator_arity(expression, 0, "no")
        return record_evaluator.Drop()
    if marker in {
        MarkerKind.FIELD,
        MarkerKind.OPTIONAL_FIELD,
        MarkerKind.READONLY_FIELD,
    }:
        _require_evaluator_arity(expression, 2, "two")
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        if marker is MarkerKind.FIELD:
            return record_evaluator.Field(*arguments)
        if marker is MarkerKind.OPTIONAL_FIELD:
            return record_evaluator.OptionalField(*arguments)
        return record_evaluator.ReadonlyField(*arguments)
    if marker is MarkerKind.MAP_FIELDS:
        _require_evaluator_arity(expression, 2, "two")
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        return record_evaluator.MapFields(arguments[0], arguments[1], output_name)
    if marker is MarkerKind.MAP:
        return adapt_evaluator_map(expression, environment)
    if marker is MarkerKind.IF:
        _require_evaluator_arity(expression, 3, "three")
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        return record_evaluator.If(*arguments)
    if marker in {MarkerKind.EQUAL, MarkerKind.ASSIGNABLE}:
        _require_evaluator_arity(expression, 2, "two")
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        if marker is MarkerKind.EQUAL:
            return record_evaluator.Equal(*arguments)
        return record_evaluator.Assignable(*arguments)
    if marker in {MarkerKind.ALL, MarkerKind.ANY}:
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        if marker is MarkerKind.ALL:
            return record_evaluator.All(arguments)
        return record_evaluator.Any(arguments)
    if marker is MarkerKind.NOT:
        _require_evaluator_arity(expression, 1, "one")
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        return record_evaluator.Not(arguments[0])
    raise EvaluatorAdaptationError(f"unsupported record expression {marker.value}")


def adapt_evaluator_expressions(
    expressions: tuple[SourceTypeExpression, ...],
    environment: tuple[tuple[str, StaticType], ...],
) -> tuple[record_evaluator.Expression, ...]:
    return tuple(
        adapt_evaluator_expression(expression, environment)
        for expression in expressions
    )


def adapt_evaluator_map(
    expression: MarkerTypeExpression,
    environment: tuple[tuple[str, StaticType], ...],
) -> record_evaluator.Expression:
    if len(expression.arguments) < 2:
        raise EvaluatorAdaptationError(
            "Map requires a subject and at least one Case or Default"
        )
    subject = adapt_evaluator_expression(expression.arguments[0], environment)
    cases: list[record_evaluator.Case] = []
    default: record_evaluator.Expression | None = None
    for entry in expression.arguments[1:]:
        if not isinstance(entry, MarkerTypeExpression):
            raise EvaluatorAdaptationError("Map entries must be Case or Default")
        arguments = adapt_evaluator_expressions(entry.arguments, environment)
        if entry.marker is MarkerKind.CASE and len(arguments) == 2:
            cases.append(record_evaluator.Case(*arguments))
        elif entry.marker is MarkerKind.DEFAULT and len(arguments) == 1:
            default = arguments[0]
        else:
            raise EvaluatorAdaptationError(
                "Map entries must be Case[Input, Output] or Default[Output]"
            )
    if default is None:
        return record_evaluator.Map(subject, tuple(cases))
    return record_evaluator.Map(subject, tuple(cases), default)


def _require_evaluator_arity(
    expression: MarkerTypeExpression,
    count: int,
    count_name: str,
) -> None:
    if len(expression.arguments) != count:
        raise EvaluatorAdaptationError(
            f"{expression.marker.value} requires {count_name} type arguments"
        )


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
    return (
        isinstance(value, MarkerTypeExpression)
        and value.marker is MarkerKind.MAP_FIELDS
    )


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
