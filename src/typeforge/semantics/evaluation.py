"""Shared semantic evaluation interface and private traversal."""

from functools import singledispatch

from returns.result import Failure, Result, safe

from typeforge.semantics.domain.assertions import expect_condition, expect_type
from typeforge.semantics.domain.exceptions import (
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
    CaseExpression,
    DropExpression,
    DroppedField,
    EqualExpression,
    EvaluationContext,
    EvaluationValue,
    Expression,
    FieldName,
    InputReference,
    KeyReference,
    MapExpression,
    NotExpression,
    ResolvedType,
    TypeReference,
    UnionExpression,
    ValueReference,
)
from typeforge.semantics.protocols import TypeSystem


def _value_or_raise[T](result: Result[T, SemanticIssue]) -> T:
    if isinstance(result, Failure):
        raise result.failure()

    return result.unwrap()


@safe(exceptions=(SemanticIssue,))
def evaluate[T](
    expression: Expression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T] | None = None,
) -> EvaluationValue[T]:
    """Evaluate a normalized expression through a type-system adapter."""
    evaluation_context = EvaluationContext[T]() if context is None else context
    return _evaluate(expression, type_system, evaluation_context)


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


@_evaluate.register(UnionExpression)
def _[T](
    expression: UnionExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    members = tuple(
        expect_type(
            _evaluate(member, type_system, context),
            "union members must evaluate to types",
        ).value
        for member in expression.members
    )
    return ResolvedType(_value_or_raise(type_system.union(members)))


@_evaluate.register(EqualExpression)
def _[T](
    expression: EqualExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    left = _evaluate(expression.left, type_system, context)
    right = _evaluate(expression.right, type_system, context)

    if isinstance(left, ResolvedType) and isinstance(right, ResolvedType):
        return _value_or_raise(type_system.equal(left.value, right.value))

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
    return _value_or_raise(type_system.assignable(source.value, target.value))


@_evaluate.register(AnyExpression | AllExpression)
def _[T](
    expression: AllExpression[T] | AnyExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    for condition in expression.conditions:
        matched = expect_condition(
            _evaluate(condition, type_system, context),
            "condition must evaluate to bool",
        )
        if isinstance(expression, AllExpression) and not matched:
            return False

        if isinstance(expression, AnyExpression) and matched:
            return True

    return isinstance(expression, AllExpression)


@_evaluate.register(NotExpression)
def _[T](
    expression: NotExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    condition = expect_condition(
        _evaluate(expression.condition, type_system, context),
        "condition must evaluate to bool",
    )
    return not condition


@_evaluate.register(MapExpression)
def _[T](
    expression: MapExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    subject = _evaluate(expression.subject, type_system, context)

    members: tuple[EvaluationValue[T], ...]
    if isinstance(subject, ResolvedType):
        native_members = _value_or_raise(type_system.union_members(subject.value))
        members = tuple(ResolvedType(member) for member in native_members)
    else:
        members = (subject,)

    outputs = tuple(
        _evaluate_map_member(
            member,
            expression.cases,
            expression.default,
            type_system,
            context,
        )
        for member in members
    )
    if len(outputs) == 1:
        return outputs[0]

    output_types = tuple(
        expect_type(
            output,
            "Map outputs for a union subject must evaluate to types",
        ).value
        for output in outputs
    )
    return ResolvedType(_value_or_raise(type_system.union(output_types)))


def _evaluate_map_member[T](
    subject: EvaluationValue[T],
    cases: tuple[CaseExpression[T], ...],
    default: Expression[T] | None,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    for case in cases:
        if isinstance(
            case.test,
            EqualExpression
            | AssignableExpression
            | AllExpression
            | AnyExpression
            | NotExpression,
        ):
            matched = expect_condition(
                _evaluate(case.test, type_system, context),
                "condition must evaluate to bool",
            )
        else:
            test = _evaluate(case.test, type_system, context)
            matched = _map_values_are_equal(subject, test, type_system)
        if matched:
            return _evaluate(case.output, type_system, context)

    if default is not None:
        return _evaluate(default, type_system, context)

    return ResolvedType(_value_or_raise(type_system.union(())))


def _map_values_are_equal[T](
    left: EvaluationValue[T],
    right: EvaluationValue[T],
    type_system: TypeSystem[T],
) -> bool:
    if isinstance(left, ResolvedType) and isinstance(right, ResolvedType):
        return _value_or_raise(type_system.equal(left.value, right.value))

    if isinstance(left, FieldName) and isinstance(right, FieldName):
        return left == right

    return False
