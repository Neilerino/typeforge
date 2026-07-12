from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Protocol

from typeforge.analysis.model import SourceSpan, VirtualDocument

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)
type JsonObject = dict[str, JsonValue]
type RequestId = int | str


class InitializeTransform(Protocol):
    def __call__(self, message: JsonObject) -> JsonObject: ...


class DiagnosticSuppressor(Protocol):
    def __call__(
        self,
        diagnostic: JsonObject,
        document: VirtualDocument,
        span: SourceSpan,
    ) -> bool: ...


def forward_initialize(message: JsonObject) -> JsonObject:
    return message


def preserve_diagnostic(
    diagnostic: JsonObject,
    document: VirtualDocument,
    span: SourceSpan,
) -> bool:
    del diagnostic, document, span
    return False


class ProxyErrorCode(StrEnum):
    SPAWN = "spawn"
    INPUT = "input"
    OUTPUT = "output"
    PROTOCOL = "protocol"
    TRANSFORM = "transform"
    BACKEND_EXIT = "backend_exit"


@dataclass(frozen=True, slots=True)
class ProxyError:
    code: ProxyErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class ProxyConfiguration:
    project_root: Path
    backend_command: tuple[str, ...]
    maximum_arity: int = 8
    initialize: InitializeTransform = forward_initialize
    suppress_diagnostic: DiagnosticSuppressor = preserve_diagnostic


@dataclass(frozen=True, slots=True)
class ProxyStreams:
    editor_input: BinaryIO
    editor_output: BinaryIO


@dataclass(frozen=True, slots=True)
class DocumentState:
    document: VirtualDocument


@dataclass(frozen=True, slots=True)
class PendingRequest:
    method: str
    uri: str | None
