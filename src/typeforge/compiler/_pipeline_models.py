"""Data and error types shared by compiler pipeline stages."""

from dataclasses import dataclass
from pathlib import Path

from typeforge.compiler.frontend import FrontendError
from typeforge.compiler.lowering import (
    IfType,
    LoweringError,
    MapType,
    ModuleImport,
    OverloadDeclaration,
)
from typeforge.compiler.records import TypedDictShape


@dataclass(frozen=True)
class AdaptationError(Exception):
    declaration: str
    expression: str
    message: str


@dataclass(frozen=True)
class EvaluatorAdaptationError(Exception):
    message: str


@dataclass(frozen=True, slots=True)
class EmissionError:
    message: str


@dataclass(frozen=True, slots=True)
class UnsupportedPublicDeclaration:
    path: Path
    line: int
    message: str


type GenerationError = (
    FrontendError
    | AdaptationError
    | LoweringError
    | EmissionError
    | UnsupportedPublicDeclaration
)


@dataclass(frozen=True, slots=True)
class GeneratedModule:
    source_path: Path
    content: str


@dataclass(frozen=True, slots=True)
class DerivedRecord:
    alias: str
    input_name: str
    shape: TypedDictShape


@dataclass(frozen=True, slots=True)
class RecordMaterialization:
    declarations: tuple[str, ...]
    replacements: tuple[tuple[str, OverloadDeclaration], ...]
    imports: tuple[ModuleImport, ...]
    derived: tuple[DerivedRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ModuleVariables:
    declarations: tuple[str, ...]
    requires_any: bool


@dataclass(frozen=True, slots=True)
class SemanticRelationshipAlias:
    name: str
    parameter: str
    relationship: MapType | IfType
