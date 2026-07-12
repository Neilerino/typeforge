from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from typeforge._result import Result


@dataclass(frozen=True, slots=True, order=True)
class SourcePosition:
    offset: int
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start: SourcePosition
    end: SourcePosition


class MappingKind(Enum):
    AUTHORED = "authored"
    GENERATED = "generated"


@dataclass(frozen=True, slots=True)
class SourceMapping:
    authored: SourceSpan
    generated: SourceSpan
    origin: MappingKind


@dataclass(frozen=True, slots=True)
class VirtualDocument:
    uri: str
    path: Path
    version: int
    authored_text: str
    generated_text: str
    mappings: tuple[SourceMapping, ...]


@dataclass(frozen=True, slots=True)
class CheckerCapabilities:
    diagnostics: bool
    hover: bool
    completion: bool
    signature_help: bool
    definitions: bool
    references: bool
    rename: bool
    code_actions: bool
    in_memory_documents: bool


class DiagnosticSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"
    HINT = "hint"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    checker: str
    path: Path
    span: SourceSpan
    severity: DiagnosticSeverity
    message: str
    code: str | None


@dataclass(frozen=True, slots=True)
class CheckerError:
    checker: str
    message: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class HoverQuery:
    position: SourcePosition


@dataclass(frozen=True, slots=True)
class HoverResult:
    checker: str
    path: Path
    span: SourceSpan | None
    contents: str


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    diagnostics: tuple[Diagnostic, ...]
    hovers: tuple[HoverResult, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    document: VirtualDocument
    project_root: Path
    config_file: Path | None = None
    extra_arguments: tuple[str, ...] = ()
    hover_queries: tuple[HoverQuery, ...] = ()


class CheckerAdapter(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> CheckerCapabilities: ...

    def analyze(
        self, request: AnalysisRequest
    ) -> Result[AnalysisResult, CheckerError]: ...
