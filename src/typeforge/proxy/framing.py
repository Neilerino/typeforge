import json
from typing import BinaryIO, cast

from typeforge._result import Err, Ok, Result
from typeforge.proxy.model import JsonObject, JsonValue, ProxyError, ProxyErrorCode


def read_message(stream: BinaryIO) -> Result[JsonObject | None, ProxyError]:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return Ok(None)
        if line in {b"\r\n", b"\n"}:
            break
        try:
            name, value = line.decode("ascii").split(":", 1)
        except UnicodeDecodeError, ValueError:
            return Err(ProxyError(ProxyErrorCode.PROTOCOL, "invalid LSP header"))
        headers[name.lower()] = value.strip()
    length_text = headers.get("content-length")
    if length_text is None:
        return Err(ProxyError(ProxyErrorCode.PROTOCOL, "missing Content-Length header"))
    try:
        length = int(length_text)
    except ValueError:
        return Err(ProxyError(ProxyErrorCode.PROTOCOL, "invalid Content-Length header"))
    payload = _read_exactly(stream, length)
    if len(payload) != length:
        return Err(ProxyError(ProxyErrorCode.PROTOCOL, "truncated LSP message"))
    try:
        decoded: object = json.loads(payload)
    except json.JSONDecodeError, UnicodeDecodeError:
        return Err(ProxyError(ProxyErrorCode.PROTOCOL, "invalid JSON-RPC payload"))
    if not isinstance(decoded, dict):
        return Err(
            ProxyError(ProxyErrorCode.PROTOCOL, "JSON-RPC payload must be an object")
        )
    untyped = cast(dict[object, object], decoded)
    if any(not isinstance(key, str) for key in untyped):
        return Err(ProxyError(ProxyErrorCode.PROTOCOL, "JSON-RPC keys must be strings"))
    return Ok(cast(JsonObject, decoded))


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


def write_message(
    stream: BinaryIO, message: dict[str, JsonValue]
) -> Result[None, ProxyError]:
    try:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        stream.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        stream.write(payload)
        stream.flush()
    except OSError as error:
        return Err(ProxyError(ProxyErrorCode.OUTPUT, str(error)))
    return Ok(None)
