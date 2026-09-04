"""Data and error types shared by compiler pipeline stages."""

from dataclasses import dataclass
from pathlib import Path

from typeforge.compiler.adaptation import AdaptationError
from typeforge.compiler.lowering import LoweringError
from typeforge.compiler.semantic_adapter import StaticType
from typeforge.compiler.source import FrontendError
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    ModuleImport,
    OverloadDeclaration,
    VariableDeclaration,
)
from typeforge.semantics import RecordShape


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
    shape: RecordShape[StaticType]


@dataclass(frozen=True, slots=True)
class RecordMaterialization:
    declarations: tuple[ClassDeclaration, ...]
    replacements: tuple[tuple[str, OverloadDeclaration], ...]
    imports: tuple[ModuleImport, ...]
    derived: tuple[DerivedRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ModuleVariables:
    declarations: tuple[VariableDeclaration, ...]
    imports: tuple[ModuleImport, ...]
