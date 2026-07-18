import json
from typing import BinaryIO, cast

from returns.result import safe

from typeforge.proxy.model import JsonObject, JsonValue, ProxyError, ProxyErrorCode


@safe(exceptions=(ProxyError,))
def read_message(stream: BinaryIO) -> JsonObject | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        try:
            name, value = line.decode("ascii").split(":", 1)
        except UnicodeDecodeError, ValueError:
            raise ProxyError("invalid LSP header") from None
        headers[name.lower()] = value.strip()
    length_text = headers.get("content-length")
    if length_text is None:
        raise ProxyError("missing Content-Length header")
    try:
        length = int(length_text)
    except ValueError:
        raise ProxyError("invalid Content-Length header") from None
    payload = _read_exactly(stream, length)
    if len(payload) != length:
        raise ProxyError("truncated LSP message")
    try:
        decoded: object = json.loads(payload)
    except json.JSONDecodeError, UnicodeDecodeError:
        raise ProxyError("invalid JSON-RPC payload") from None
    if not isinstance(decoded, dict):
        raise ProxyError("JSON-RPC payload must be an object")
    untyped = cast(dict[object, object], decoded)
    if any(not isinstance(key, str) for key in untyped):
        raise ProxyError("JSON-RPC keys must be strings")
    return cast(JsonObject, decoded)


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


@safe(exceptions=(ProxyError,))
def write_message(stream: BinaryIO, message: dict[str, JsonValue]) -> None:
    try:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        stream.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        stream.write(payload)
        stream.flush()
    except OSError as error:
        raise ProxyError(
            str(error),
            ProxyErrorCode.OUTPUT,
        ) from error
