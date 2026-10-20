"""Data and error types shared by compiler pipeline stages."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from typeforge.compiler.adaptation import AdaptationError
from typeforge.compiler.emission import EmissionError
from typeforge.compiler.module_surface import UnsupportedPublicDeclaration
from typeforge.compiler.record_materialization import RecordMaterializationError
from typeforge.compiler.source import (
    FrontendError,
    SourceModule,
    SourceSpan,
    SourceSyntaxError,
)
from typeforge.compiler.specialization import LoweringError
from typeforge.compiler.stub_ir import StubModule, StubTypeExpression
from typeforge.compiler.verification import VerificationPlan

type CompilationError = (
    SourceSyntaxError | AdaptationError | LoweringError | RecordMaterializationError
)

type GenerationError = (
    FrontendError
    | AdaptationError
    | LoweringError
    | RecordMaterializationError
    | EmissionError
    | UnsupportedPublicDeclaration
)


@dataclass(frozen=True, slots=True)
class CompilationPlan:
    source: SourceModule
    module: StubModule
    verification: VerificationPlan


@dataclass(frozen=True, slots=True)
class GeneratedModule:
    source_path: Path
    content: str


@dataclass(frozen=True, slots=True)
class TypeParameterProjection:
    name: str
    domain: StubTypeExpression
    span: SourceSpan


class AuthoredParameterKind(StrEnum):
    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"


@dataclass(frozen=True, slots=True)
class AuthoredParameter:
    name: str
    kind: AuthoredParameterKind
    annotation: str | None
    has_default: bool


@dataclass(frozen=True, slots=True)
class AuthoredCallable:
    qualified_name: tuple[str, ...]
    parameters: tuple[AuthoredParameter, ...]
    return_annotation: str | None

    @property
    def display_name(self) -> str:
        return ".".join(self.qualified_name)
