"""Translate shared evaluation outcomes at the runtime integration boundary."""

from returns.result import Failure, Result, Success

from typeforge import semantics as s
from typeforge.pydantic._errors import (
    SchemaIssue,
    UnresolvedAnnotationIssue,
    UnsupportedRecordIssue,
)
from typeforge.pydantic._frontend import (
    AdaptedAnnotation,
    has_parameters,
    uses_generic_fallback,
)
from typeforge.pydantic._policy import no_match_issue
from typeforge.pydantic._records import UnresolvedRecordAnnotation, UnsupportedRecord
from typeforge.pydantic._type_system import RuntimeType


def evaluation_issue(
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


def schema_output(
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
