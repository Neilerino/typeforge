from dataclasses import dataclass
from enum import StrEnum

from typeforge.analysis.model import SourceSpan
from typeforge.compiler.lowering import MapType, TypeExpression


class GuardMode(StrEnum):
    EXACT = "exact"
    INSTANCE = "instance"


@dataclass(frozen=True, slots=True)
class Guard:
    symbol: str
    type_names: tuple[str, ...]
    mode: GuardMode


@dataclass(frozen=True, slots=True)
class Alternative:
    index: int
    input_type: TypeExpression | None
    output_type: TypeExpression
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class ReturnContract:
    qualified_name: tuple[str, ...]
    return_annotation: str
    controller_parameter: str
    controller_type_parameter: str
    mapping: MapType
    alternatives: tuple[Alternative, ...]


@dataclass(frozen=True, slots=True)
class FlowState:
    alternatives: tuple[int, ...]
    refined: bool = False
    controller_valid: bool = True


@dataclass(frozen=True, slots=True)
class ReturnObligation:
    qualified_name: tuple[str, ...]
    return_annotation: str
    controller_parameter: str
    expected_types: tuple[TypeExpression, ...]
    narrowed_inputs: tuple[str, ...]
    expression_text: str
    expression_span: SourceSpan
    insertion_offset: int
    indentation: str
    inline: bool
    starts_line: bool = False
    leading_newline: bool = False


@dataclass(frozen=True, slots=True)
class VerificationPlan:
    obligations: tuple[ReturnObligation, ...]
    reserved_names: tuple[str, ...]
