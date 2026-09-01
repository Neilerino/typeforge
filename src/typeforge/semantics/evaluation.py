"""Shared semantic evaluation interface and private traversal."""

from functools import singledispatch

from returns.result import safe

from typeforge.semantics.domain.exceptions import (
    SemanticIssue,
    UnboundInputSemanticError,
    UnboundKeySemanticError,
    UnboundValueSemanticError,
    UnsupportedExpressionSemanticError,
)
from typeforge.semantics.domain.models import (
    DropExpression,
    DroppedField,
    EvaluationContext,
    EvaluationValue,
    Expression,
    FieldName,
    InputReference,
    KeyReference,
    ResolvedType,
    TypeReference,
    ValueReference,
)
from typeforge.semantics.protocols import TypeSystem


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
