from dataclasses import dataclass
from enum import StrEnum

from typeforge.compiler.source import FunctionDeclaration, ReturnSite, SourceSpan
from typeforge.compiler.stub_ir import MapType, StubTypeExpression


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
    input_type: StubTypeExpression | None
    output_type: StubTypeExpression
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class ReturnContract:
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
class ImplicitReturnSite:
    suite: SourceSpan


@dataclass(frozen=True, slots=True)
class ReturnObligation:
    function: FunctionDeclaration
    contract: ReturnContract
    site: ReturnSite | ImplicitReturnSite
    expected_types: tuple[StubTypeExpression, ...]
    narrowed_inputs: tuple[StubTypeExpression, ...]


@dataclass(frozen=True, slots=True)
class VerificationPlan:
    obligations: tuple[ReturnObligation, ...]
