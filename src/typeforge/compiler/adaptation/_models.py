"""Data and modeled failures produced by source adaptation."""

from dataclasses import dataclass

from typeforge.compiler.stub_ir import MapType
from typeforge.semantics import UnresolvedCaptureSemanticError


@dataclass(frozen=True)
class AdaptationError(Exception):
    declaration: str
    expression: str
    message: str
    unresolved_capture: UnresolvedCaptureSemanticError | None = None


@dataclass(frozen=True, slots=True)
class SemanticRelationshipAlias:
    name: str
    parameter: str
    relationship: MapType
