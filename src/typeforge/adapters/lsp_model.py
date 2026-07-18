from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Literal

from pydantic.dataclasses import dataclass as validated_dataclass

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr
from typeforge.utils.stream import JsonValue


@validated_dataclass(frozen=True, slots=True, config=ConfigDict(extra="ignore"))
class LspPosition:
    line: StrictInt
    character: StrictInt


@validated_dataclass(frozen=True, slots=True, config=ConfigDict(extra="ignore"))
class LspRange:
    start: LspPosition
    end: LspPosition


@dataclass(frozen=True, slots=True)
class LspDocument:
    uri: str
    text: str
    version: int = 1
    language_id: str = "python"


@validated_dataclass(frozen=True, slots=True, config=ConfigDict(extra="ignore"))
class LspDiagnostic:
    range: LspRange
    message: StrictStr
    severity: StrictInt | None = None
    code: StrictStr | StrictInt | None = None
    source: StrictStr | None = None


class DiagnosticsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    uri: str
    diagnostics: list[LspDiagnostic]


class PublishedDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    method: Literal["textDocument/publishDiagnostics"]
    params: DiagnosticsParams


class DiagnosticReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    items: list[LspDiagnostic] | None = None


class HoverResultPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    contents: JsonValue
    range: LspRange | None = None


@dataclass(frozen=True, slots=True)
class LspHover:
    position: LspPosition
    contents: str | None
    range: LspRange | None = None


@dataclass(frozen=True, slots=True)
class LspAnalysis:
    diagnostics: tuple[LspDiagnostic, ...]
    hovers: tuple[LspHover, ...]


@dataclass(frozen=True, slots=True)
class Response:
    result: JsonValue
    diagnostics: tuple[LspDiagnostic, ...] | None


class LspErrorCode(StrEnum):
    SPAWN = "spawn"
    TIMEOUT = "timeout"
    PROTOCOL = "protocol"
    SERVER = "server"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class LspError(Exception):
    message: str
    code: ClassVar[LspErrorCode]


class LspSpawnError(LspError):
    code = LspErrorCode.SPAWN


class LspTimeoutError(LspError):
    code = LspErrorCode.TIMEOUT


class LspProtocolError(LspError):
    code = LspErrorCode.PROTOCOL


class LspServerError(LspError):
    code = LspErrorCode.SERVER


class LspExitError(LspError):
    code = LspErrorCode.EXIT


@dataclass(frozen=True, slots=True)
class LspConfiguration:
    command: tuple[str, ...]
    root: Path
    initialization_options: Mapping[str, JsonValue] | None = None
    timeout_seconds: float = 10.0
