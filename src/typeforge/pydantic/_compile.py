"""Orchestrate adaptation, shared evaluation, policy, and Pydantic emission."""

from pydantic_core import CoreSchema
from returns.result import Failure, Result, Success

from pydantic import GetCoreSchemaHandler
from typeforge import semantics as s
from typeforge.pydantic._emission import emit_no_match, emit_type
from typeforge.pydantic._errors import MapNoMatchIssue, SchemaIssue
from typeforge.pydantic._frontend import (
    AdaptedAnnotation,
    adapt_annotation,
    has_parameters,
    uses_generic_fallback,
)
from typeforge.pydantic._policy import PydanticEvaluationPolicy, no_match_issue
from typeforge.pydantic._type_system import RUNTIME_TYPE_SYSTEM, RuntimeType


def compile_annotation(
    source: object, handler: GetCoreSchemaHandler
) -> Result[CoreSchema, SchemaIssue]:
    return _recover_generic_no_match(
        Result.do(
            schema
            for adapted in adapt_annotation(source).alt(
                lambda issue: _adaptation_issue(issue, source)
            )
            for evaluated in _evaluate_annotation(adapted, source)
            for output in _resolved_type(evaluated, source)
            for schema in emit_type(output, handler, source)
        )
    )


def _adaptation_issue(
    issue: SchemaIssue | s.SemanticIssue, source: object
) -> SchemaIssue:
    if isinstance(issue, SchemaIssue):
        return issue

    return SchemaIssue(str(issue.code), "parsing", source, issue.message)


def _evaluate_annotation(
    adapted: AdaptedAnnotation, source: object
) -> Result[s.EvaluationValue[RuntimeType], SchemaIssue]:
    return (
        s.Evaluator(RUNTIME_TYPE_SYSTEM, policy=PydanticEvaluationPolicy())
        .evaluate(adapted.expression)
        .alt(lambda issue: _evaluation_issue(issue, adapted, source))
    )


def _evaluation_issue(
    outcome: s.SemanticIssue | s.MapNoMatch[RuntimeType],
    adapted: AdaptedAnnotation,
    source: object,
) -> SchemaIssue:
    if isinstance(outcome, s.SemanticIssue):
        return SchemaIssue(str(outcome.code), "evaluation", source, outcome.message)

    authored = adapted.origins[id(outcome.expression)]
    subject = (
        outcome.subject.value.value
        if isinstance(outcome.subject, s.ResolvedType)
        else source
    )
    return no_match_issue(
        authored,
        subject,
        uses_generic_fallback=(
            isinstance(outcome.subject, s.ResolvedType)
            and has_parameters(outcome.subject.value.annotation)
        )
        or any(
            uses_generic_fallback(operand)
            for operand in (
                outcome.expression.subject,
                *(case.test for case in outcome.expression.cases),
            )
        ),
    )


def _resolved_type(
    value: s.EvaluationValue[RuntimeType], source: object
) -> Result[RuntimeType, SchemaIssue]:
    if isinstance(value, s.ResolvedType):
        return Success(value.value)

    return Failure(
        SchemaIssue(
            "expected_type",
            "evaluation",
            source,
            "Schema expression must resolve to a type",
        )
    )


def _recover_generic_no_match(
    result: Result[CoreSchema, SchemaIssue],
) -> Result[CoreSchema, SchemaIssue]:
    if isinstance(result, Failure):
        issue = result.failure()
        # Keep an uninhabited generic origin available for later specialization.
        if isinstance(issue, MapNoMatchIssue) and issue.uses_generic_fallback:
            return Success(emit_no_match(issue))

    return result
