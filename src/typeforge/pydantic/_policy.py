"""Integration rules kept separate from reflection and schema emission."""

from typeforge.pydantic._errors import MapNoMatchIssue
from typeforge.semantics import EvaluationMode, MapNoMatch, NoMatchDecision


class PydanticEvaluationPolicy[T]:
    """Reject reached no-match paths, while allowing possible-output exploration."""

    def no_match(self, outcome: MapNoMatch[T]) -> NoMatchDecision:
        return (
            NoMatchDecision.REJECT
            if outcome.context.mode is EvaluationMode.DEFINITE
            else NoMatchDecision.ACCEPT
        )


def generic_fallback[T](
    *, default: T | None, constraints: tuple[T, ...], bound: T | None, any_type: T
) -> tuple[T, ...]:
    if default is not None:
        return (default,)

    if constraints:
        return constraints

    return (bound,) if bound is not None else (any_type,)


def no_match_issue(
    expression: object, subject: object, *, uses_generic_fallback: bool
) -> MapNoMatchIssue:
    return MapNoMatchIssue(
        code="map_no_match",
        phase="evaluation",
        expression=expression,
        message="Map cannot determine an output type: "
        "no case matched and no default was provided",
        uses_generic_fallback=uses_generic_fallback,
        subject=subject,
    )
