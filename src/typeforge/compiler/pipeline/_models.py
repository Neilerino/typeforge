"""Data and error types shared by compiler pipeline stages."""

from dataclasses import dataclass
from pathlib import Path

from typeforge.compiler.adaptation import AdaptationError
from typeforge.compiler.emission import EmissionError
from typeforge.compiler.module_surface import UnsupportedPublicDeclaration
from typeforge.compiler.record_materialization import RecordMaterializationError
from typeforge.compiler.source import FrontendError
from typeforge.compiler.specialization import LoweringError

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
