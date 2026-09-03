"""Evaluate compiler source expressions through shared semantics."""

from returns.result import Failure, Result

from typeforge.compiler._semantic_lowering import (
    SemanticEnvironment,
    SemanticLoweringError,
    lower_semantic_expression,
)
from typeforge.compiler._type_system import COMPILER_TYPE_SYSTEM
from typeforge.compiler.model import TypeExpression as SourceTypeExpression
from typeforge.compiler.records import StaticType
from typeforge.semantics import EvaluationValue, SemanticIssue, evaluate

type CompilerSemanticIssue = SemanticLoweringError | SemanticIssue


def evaluate_source_semantics(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment = (),
    output_name: str | None = None,
) -> Result[EvaluationValue[StaticType], CompilerSemanticIssue]:
    """Lower and evaluate one authored expression through compiler semantics."""
    try:
        semantic_expression = lower_semantic_expression(
            expression,
            environment,
            output_name,
        )
    except SemanticLoweringError as error:
        return Failure(error)

    return evaluate(semantic_expression, COMPILER_TYPE_SYSTEM)
