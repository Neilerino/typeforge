"""Configuration and modeled failures for finite specialization."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class ArityFrontier:
    minimum: int = 0
    maximum: int = 8


class LoweringErrorCode(StrEnum):
    INVALID_FRONTIER = "invalid_frontier"
    INVALID_EACH_POSITION = "invalid_each_position"
    MISSING_CAPTURE = "missing_capture"
    MULTIPLE_CAPTURES = "multiple_captures"
    MISSING_CONTROLLER = "missing_controller"
    UNSUPPORTED_PREDICATE = "unsupported_predicate"
    DUPLICATE_MAP_CASE = "duplicate_map_case"
    UNREPRESENTABLE_COVERAGE = "unrepresentable_coverage"
    UNREPRESENTABLE_OUTPUT = "unrepresentable_output"


@dataclass(frozen=True, slots=True)
class LoweringError:
    code: LoweringErrorCode
    declaration: str
    message: str
