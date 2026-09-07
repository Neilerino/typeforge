"""Orchestrate adaptation, shared evaluation, policy, and Pydantic emission."""

from pydantic_core import CoreSchema
from returns.result import Failure, Result, Success

from pydantic import GetCoreSchemaHandler
from typeforge import semantics as s
from typeforge.pydantic._deferred import DeferredAnnotations
from typeforge.pydantic._emission import emit_generic_failure, emit_output
from typeforge.pydantic._errors import (
    MapNoMatchIssue,
    SchemaIssue,
    UnsupportedRecordIssue,
)
from typeforge.pydantic._evaluation import evaluation_issue, schema_output
from typeforge.pydantic._frontend import (
    AdaptedAnnotation,
    adapt_annotation,
)
from typeforge.pydantic._policy import PydanticEvaluationPolicy
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
            for output in schema_output(evaluated, source)
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
        s.Evaluator(
            RUNTIME_TYPE_SYSTEM,
            policy=PydanticEvaluationPolicy(),
            deferred_types=DeferredAnnotations(adapted, source),
        )
        .evaluate(adapted.expression)
        .alt(lambda issue: evaluation_issue(issue, adapted, source))
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
