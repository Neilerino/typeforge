"""Shared semantic evaluation interface and private traversal."""

from dataclasses import replace
from functools import singledispatch

from returns.primitives.exceptions import UnwrapFailedError
from returns.result import Result, safe

from typeforge.semantics.domain.assertions import (
    expect_condition,
    expect_field,
    expect_field_name,
    expect_type,
)
from typeforge.semantics.domain.exceptions import (
    DuplicateFieldSemanticError,
    ExpectedTypeSemanticError,
    SemanticIssue,
    UnboundInputSemanticError,
    UnboundKeySemanticError,
    UnboundValueSemanticError,
    UnsupportedExpressionSemanticError,
)
from typeforge.semantics.domain.models import (
    AllExpression,
    AnyExpression,
    AssignableExpression,
    DropExpression,
    DroppedField,
    EqualExpression,
    EvaluationContext,
    EvaluationValue,
    Expression,
    FieldExpression,
    FieldName,
    IndeterminateCondition,
    InputReference,
    KeyReference,
    MapExpression,
    MapFieldsExpression,
    NotExpression,
    OptionalFieldExpression,
    ParameterizedTypeResolution,
    ParameterizedTypeShape,
    ParameterizedTypeTemplate,
    ReadonlyFieldExpression,
    RecordField,
    ResolvedType,
    TypeReference,
    UnionExpression,
    UnresolvedType,
    UnresolvedTypeReference,
    ValueReference,
)
from typeforge.semantics.map_evaluation import evaluate_map
from typeforge.semantics.protocols import TypeSystem


def evaluate[T](
    expression: Expression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T] | None = None,
) -> Result[EvaluationValue[T], SemanticIssue]:
    """Evaluate a normalized expression through a type-system adapter."""
    evaluation_context = EvaluationContext[T]() if context is None else context

    eval_safely = safe(exceptions=(SemanticIssue, UnwrapFailedError))(_evaluate)
    return eval_safely(expression, type_system, evaluation_context).alt(_semantic_issue)


def _semantic_issue(error: Exception) -> SemanticIssue:
    if isinstance(error, SemanticIssue):
        return error

    if isinstance(error, UnwrapFailedError) and isinstance(
        error.__cause__, SemanticIssue
    ):
        return error.__cause__

    raise error


@singledispatch
def _evaluate[T](
    expression: Expression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    raise UnsupportedExpressionSemanticError(
        f"unsupported expression {type(expression).__name__}"
    )


@_evaluate.register(TypeReference)
def _[T](
    expression: TypeReference[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return ResolvedType(expression.value)


@_evaluate.register(UnresolvedTypeReference)
def _[T](
    expression: UnresolvedTypeReference[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return UnresolvedType(expression.value)


@_evaluate.register(FieldName)
def _[T](
    expression: FieldName,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return expression


@_evaluate.register(InputReference)
def _[T](
    expression: InputReference,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    if context.input_type is None:
        raise UnboundInputSemanticError("Input requires value-time evaluation")

    return context.input_type


@_evaluate.register(KeyReference)
def _[T](
    expression: KeyReference,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    if context.key is None:
        raise UnboundKeySemanticError("Key requires MapFields")

    return FieldName(context.key)


@_evaluate.register(ValueReference)
def _[T](
    expression: ValueReference,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    if context.capture is not None:
        return context.capture

    if context.value is not None:
        return context.value

    raise UnboundValueSemanticError("Value requires MapFields or a structural Map case")


@_evaluate.register(DropExpression)
def _[T](
    expression: DropExpression,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return DroppedField()


@_evaluate.register(ParameterizedTypeTemplate)
def _[T](
    expression: ParameterizedTypeTemplate[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    resolved_arguments = tuple(
        expect_type(
            _evaluate(argument, type_system, context),
            "parameterized type arguments must evaluate to types",
        )
        for argument in expression.arguments
    )
    arguments = tuple(argument.value for argument in resolved_arguments)
    shape = ParameterizedTypeShape(expression.origin, arguments)
    value = type_system.build(shape).unwrap()
    if any(isinstance(argument, UnresolvedType) for argument in resolved_arguments):
        return UnresolvedType(
            value,
            ParameterizedTypeResolution(expression.origin, resolved_arguments),
        )
    return ResolvedType(value)


@_evaluate.register(FieldExpression | OptionalFieldExpression | ReadonlyFieldExpression)
def _[T](
    expression: (
        FieldExpression[T] | OptionalFieldExpression[T] | ReadonlyFieldExpression[T]
    ),
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    name = expect_field_name(_evaluate(expression.name, type_system, context))
    value = expect_type(
        _evaluate(expression.value, type_system, context),
        "field value must evaluate to a type",
    )

    return RecordField(
        name.value,
        value.value,
        required=not isinstance(expression, OptionalFieldExpression),
        readonly=isinstance(expression, ReadonlyFieldExpression),
    )


@_evaluate.register(MapFieldsExpression)
def _[T](
    expression: MapFieldsExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    record_type = expect_type(
        _evaluate(expression.record, type_system, context),
    )
    record = type_system.record(record_type.value).unwrap()
    fields: list[RecordField[T]] = []
    field_names: set[str] = set()

    for source_field in record.fields:
        field_context = replace(
            context,
            key=source_field.name,
            value=ResolvedType(source_field.value),
        )
        transformed = _evaluate(expression.transform, type_system, field_context)
        if isinstance(transformed, DroppedField):
            continue

        field = expect_field(
            transformed,
            "MapFields transform must evaluate to a field or Drop",
        )
        if field.name in field_names:
            raise DuplicateFieldSemanticError(
                f"multiple source fields produce {field.name!r}"
            )

        field_names.add(field.name)
        fields.append(field)

    return replace(
        record,
        name=(
            record.name if expression.output_name is None else expression.output_name
        ),
        fields=tuple(fields),
    )


@_evaluate.register(UnionExpression)
def _[T](
    expression: UnionExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    resolved_members = tuple(
        expect_type(
            _evaluate(member, type_system, context),
            "union members must evaluate to types",
        )
        for member in expression.members
    )
    members = tuple(member.value for member in resolved_members)
    value = type_system.union(members).unwrap()
    if any(isinstance(member, UnresolvedType) for member in resolved_members):
        return UnresolvedType(value)
    return ResolvedType(value)


@_evaluate.register(EqualExpression)
def _[T](
    expression: EqualExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    left = _evaluate(expression.left, type_system, context)
    right = _evaluate(expression.right, type_system, context)

    if isinstance(left, ResolvedType) and isinstance(right, ResolvedType):
        equal = type_system.equal(left.value, right.value).unwrap()
        if equal:
            return True
        if isinstance(left, UnresolvedType) or isinstance(right, UnresolvedType):
            return IndeterminateCondition()
        return False

    if isinstance(left, FieldName) and isinstance(right, FieldName):
        return left == right

    raise ExpectedTypeSemanticError(
        "Equal operands must both be types or both be field names"
    )


@_evaluate.register(AssignableExpression)
def _[T](
    expression: AssignableExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    source = expect_type(
        _evaluate(expression.source, type_system, context),
        "Assignable operands must both be types",
    )
    target = expect_type(
        _evaluate(expression.target, type_system, context),
        "Assignable operands must both be types",
    )

    assignable = type_system.assignable(source.value, target.value).unwrap()
    if assignable:
        return True
    if isinstance(source, UnresolvedType) or isinstance(target, UnresolvedType):
        return IndeterminateCondition()
    return False


@_evaluate.register(AnyExpression | AllExpression)
def _[T](
    expression: AllExpression[T] | AnyExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    has_indeterminate = False
    for condition in expression.conditions:
        evaluated = _evaluate(condition, type_system, context)
        if isinstance(evaluated, IndeterminateCondition):
            has_indeterminate = True
            continue

        matched = expect_condition(evaluated)
        if isinstance(expression, AllExpression) and not matched:
            return False

        if isinstance(expression, AnyExpression) and matched:
            return True

    if has_indeterminate:
        return IndeterminateCondition()
    return isinstance(expression, AllExpression)


@_evaluate.register(NotExpression)
def _[T](
    expression: NotExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    condition = _evaluate(expression.condition, type_system, context)
    if isinstance(condition, IndeterminateCondition):
        return condition
    return not expect_condition(condition)


@_evaluate.register(MapExpression)
def _[T](
    expression: MapExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return evaluate_map(expression, type_system, context, fn=_evaluate)
