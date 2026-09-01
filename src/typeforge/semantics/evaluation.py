"""Shared semantic evaluation interface."""

from returns.result import Failure, Result, Success

from typeforge.semantics.errors import SemanticIssue, SemanticIssueCode
from typeforge.semantics.model import (
    EvaluationContext,
    EvaluationValue,
    Expression,
    ResolvedType,
    TypeReference,
)
from typeforge.semantics.protocols import TypeSystem


def evaluate[T](
    expression: Expression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T] | None = None,
) -> Result[EvaluationValue[T], SemanticIssue]:
    """Evaluate a normalized expression through a type-system adapter."""
    del type_system, context
    if isinstance(expression, TypeReference):
        return Success(ResolvedType(expression.value))
    return Failure(
        SemanticIssue(
            SemanticIssueCode.UNSUPPORTED_EXPRESSION,
            f"unsupported expression {type(expression).__name__}",
        )
    )
