import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import BinaryIO

from returns.result import safe

from pydantic import JsonValue as PydanticJsonValue
from pydantic import TypeAdapter, ValidationError

type JsonValue = PydanticJsonValue
type JsonObject = dict[str, JsonValue]

_JSON_OBJECT_ADAPTER: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


@dataclass(frozen=True, slots=True)
class LspStreamError(Exception):
    message: str


@safe(exceptions=(LspStreamError,))
def read_lsp_message(stream: BinaryIO) -> JsonObject | None:
    headers = _read_headers(stream)
    if headers is None:
        return None
    length = _content_length(headers)
    payload = _read_exactly(stream, length)
    if len(payload) != length:
        raise LspStreamError("truncated LSP message")
    return _read_payload(payload)


@safe(exceptions=(LspStreamError,))
def write_lsp_message(stream: BinaryIO, message: Mapping[str, JsonValue]) -> None:
    try:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        stream.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        stream.write(payload)
        stream.flush()
    except OSError as error:
        raise LspStreamError(str(error)) from error


def _read_headers(stream: BinaryIO) -> dict[str, str] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            if not headers:
                return None
            raise LspStreamError("unexpected end of stream while reading headers")
        if line in {b"\r\n", b"\n"}:
            return headers
        try:
            name, value = line.decode("ascii").split(":", 1)
        except (UnicodeDecodeError, ValueError) as error:
            raise LspStreamError("invalid LSP header") from error
        headers[name.lower()] = value.strip()


def _content_length(headers: dict[str, str]) -> int:
    length_text = headers.get("content-length")
    if length_text is None:
        raise LspStreamError("missing Content-Length header")
    try:
        length = int(length_text)
    except ValueError as error:
        raise LspStreamError("invalid Content-Length header") from error
    if length < 0:
        raise LspStreamError("invalid Content-Length header")
    return length


def _read_exactly(stream: BinaryIO, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_payload(data: bytes) -> JsonObject:
    try:
        decoded: object = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise LspStreamError("invalid JSON-RPC payload") from error
    if not isinstance(decoded, dict):
        raise LspStreamError("JSON-RPC payload must be an object")
    try:
        return _JSON_OBJECT_ADAPTER.validate_python(decoded, strict=True)
    except ValidationError as error:
        raise LspStreamError("invalid JSON-RPC payload") from error
