"""Orchestrate adaptation, shared evaluation, policy, and Pydantic emission."""

from pydantic_core import CoreSchema
from returns.result import Failure, Result, Success

from pydantic import GetCoreSchemaHandler
from typeforge import semantics as s
from typeforge.pydantic._emission import emit_generic_failure, emit_output
from typeforge.pydantic._errors import (
    MapNoMatchIssue,
    SchemaIssue,
    UnresolvedAnnotationIssue,
    UnsupportedRecordIssue,
)
from typeforge.pydantic._frontend import (
    AdaptedAnnotation,
    adapt_annotation,
    has_parameters,
    uses_generic_fallback,
)
from typeforge.pydantic._policy import PydanticEvaluationPolicy, no_match_issue
from typeforge.pydantic._records import UnresolvedRecordAnnotation, UnsupportedRecord
from typeforge.pydantic._type_system import RUNTIME_TYPE_SYSTEM, RuntimeType


def compile_annotation(
    source: object, handler: GetCoreSchemaHandler
) -> Result[CoreSchema, SchemaIssue]:
    return _recover_generic_failure(
        Result.do(
            schema
            for adapted in adapt_annotation(source).alt(
                lambda issue: _adaptation_issue(issue, source)
            )
            for evaluated in _evaluate_annotation(adapted, source)
            for output in _schema_output(evaluated, source)
            for schema in emit_output(output, handler, source)
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
    if isinstance(outcome, UnsupportedRecord):
        return UnsupportedRecordIssue(
            "unsupported_record",
            "evaluation",
            source,
            outcome.message,
            uses_generic_fallback=has_parameters(outcome.annotation),
            subject=outcome.subject,
        )

    if isinstance(outcome, UnresolvedRecordAnnotation):
        return UnresolvedAnnotationIssue(
            "unresolved_annotation", "evaluation", source, outcome.message, outcome.name
        )

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


def _schema_output(
    value: s.EvaluationValue[RuntimeType], source: object
) -> Result[RuntimeType | s.RecordShape[RuntimeType], SchemaIssue]:
    if isinstance(value, s.ResolvedType):
        return Success(value.value)

    if isinstance(value, s.RecordShape):
        return Success(value)

    return Failure(
        SchemaIssue(
            "expected_type",
            "evaluation",
            source,
            "Schema expression must resolve to a type",
        )
    )


def _recover_generic_failure(
    result: Result[CoreSchema, SchemaIssue],
) -> Result[CoreSchema, SchemaIssue]:
    if isinstance(result, Failure):
        issue = result.failure()
        # Keep an uninhabited generic origin available for later specialization.
        if (
            isinstance(issue, MapNoMatchIssue | UnsupportedRecordIssue)
            and issue.uses_generic_fallback
        ):
            return Success(emit_generic_failure(issue))

    return result
