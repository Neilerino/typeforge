"""Integration rules kept separate from reflection and schema emission."""

from enum import StrEnum

from typeforge.pydantic._errors import MapNoMatchIssue, SchemaIssue


class InputTestKind(StrEnum):
    """Value-time test facts supplied by a frontend, without executing a test."""

    TYPE = "type"
    PREDICATE = "predicate"
    INPUT = "input"
    UNBOUND_VALUE = "unbound_value"
    PARAMETERIZED = "parameterized"
    UNSUPPORTED = "unsupported"


def input_test_issue(kind: InputTestKind, expression: object) -> SchemaIssue | None:
    match kind:
        case InputTestKind.TYPE | InputTestKind.PREDICATE | InputTestKind.INPUT:
            return None

        case InputTestKind.UNBOUND_VALUE:
            return SchemaIssue(
                "unbound_value",
                "planning",
                expression,
                "Value requires a field or capture binding",
            )

        case InputTestKind.PARAMETERIZED:
            message = "Input does not support parameterized runtime patterns"

        case InputTestKind.UNSUPPORTED:
            message = "unsupported Input case test"

    return SchemaIssue("unsupported_runtime_pattern", "planning", expression, message)


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
