"""Data and error types shared by compiler pipeline stages."""

from dataclasses import dataclass
from pathlib import Path

from typeforge.compiler.adaptation import AdaptationError
from typeforge.compiler.record_materialization import RecordMaterializationError
from typeforge.compiler.source import FrontendError
from typeforge.compiler.specialization import LoweringError
from typeforge.compiler.stub_ir import ModuleImport, VariableDeclaration


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
    | RecordMaterializationError
    | EmissionError
    | UnsupportedPublicDeclaration
)


@dataclass(frozen=True, slots=True)
class GeneratedModule:
    source_path: Path
    content: str


@dataclass(frozen=True, slots=True)
class ModuleVariables:
    declarations: tuple[VariableDeclaration, ...]
    imports: tuple[ModuleImport, ...]
