"""Data and modeled failures produced by source adaptation."""

from dataclasses import dataclass

from typeforge.compiler.stub_ir import MapType


@dataclass(frozen=True)
class AdaptationError(Exception):
    declaration: str
    expression: str
    message: str


@dataclass(frozen=True, slots=True)
class SemanticRelationshipAlias:
    name: str
    parameter: str
    relationship: MapType
