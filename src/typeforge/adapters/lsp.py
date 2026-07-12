from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, cast

from typeforge._result import Err, Ok, Result

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)


@dataclass(frozen=True, slots=True)
class LspPosition:
    line: int
    character: int


@dataclass(frozen=True, slots=True)
class LspRange:
    start: LspPosition
    end: LspPosition


@dataclass(frozen=True, slots=True)
class LspDocument:
    uri: str
    text: str
    version: int = 1
    language_id: str = "python"


@dataclass(frozen=True, slots=True)
class LspDiagnostic:
    uri: str
    range: LspRange
    message: str
    severity: int | None = None
    code: str | int | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class LspHover:
    position: LspPosition
    contents: str | None
    range: LspRange | None = None


@dataclass(frozen=True, slots=True)
class LspAnalysis:
    diagnostics: tuple[LspDiagnostic, ...]
    hovers: tuple[LspHover, ...]


class LspErrorCode(StrEnum):
    SPAWN = "spawn"
    TIMEOUT = "timeout"
    PROTOCOL = "protocol"
    SERVER = "server"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class LspError:
    code: LspErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class LspConfiguration:
    command: tuple[str, ...]
    root: Path
    initialization_options: Mapping[str, JsonValue] | None = None
    timeout_seconds: float = 10.0


@dataclass(frozen=True, slots=True)
class _IncomingMessage:
    value: dict[str, JsonValue] | None
    error: str | None = None


def analyze_document(
    configuration: LspConfiguration,
    document: LspDocument,
    hover_positions: tuple[LspPosition, ...] = (),
) -> Result[LspAnalysis, LspError]:
    try:
        process = subprocess.Popen(
            configuration.command,
            cwd=configuration.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        return Err(LspError(LspErrorCode.SPAWN, str(error)))
    if process.stdin is None or process.stdout is None:
        process.kill()
        return Err(LspError(LspErrorCode.SPAWN, "language server pipes unavailable"))
    writer = cast(BinaryIO, process.stdin)
    reader_stream = cast(BinaryIO, process.stdout)

    messages: queue.Queue[_IncomingMessage] = queue.Queue()
    reader = threading.Thread(
        target=_read_messages,
        args=(reader_stream, messages),
        daemon=True,
    )
    reader.start()
    deadline = time.monotonic() + configuration.timeout_seconds
    diagnostics: tuple[LspDiagnostic, ...] | None = None
    hovers: list[LspHover] = []
    next_request_id = 1

    try:
        initialize = _request(
            writer,
            next_request_id,
            "initialize",
            _initialize_parameters(configuration, document),
        )
        if isinstance(initialize, Err):
            return initialize
        initialized = _await_response(
            process,
            writer,
            messages,
            next_request_id,
            deadline,
            document.uri,
        )
        if isinstance(initialized, Err):
            return initialized
        next_request_id += 1
        notified = _notify(writer, "initialized", {})
        if isinstance(notified, Err):
            return notified
        opened = _notify(
            writer,
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": document.uri,
                    "languageId": document.language_id,
                    "version": document.version,
                    "text": document.text,
                }
            },
        )
        if isinstance(opened, Err):
            return opened

        diagnostic_response: Result[_Response, LspError] = Err(
            LspError(LspErrorCode.SERVER, "diagnostic request was not attempted")
        )
        for _ in range(3):
            pulled = _request(
                writer,
                next_request_id,
                "textDocument/diagnostic",
                {"textDocument": {"uri": document.uri}},
            )
            if isinstance(pulled, Err):
                return pulled
            diagnostic_response = _await_response(
                process,
                writer,
                messages,
                next_request_id,
                deadline,
                document.uri,
            )
            next_request_id += 1
            if not _is_mutation_cancellation(diagnostic_response):
                break
        if isinstance(diagnostic_response, Ok):
            if diagnostic_response.value.diagnostics is not None:
                diagnostics = diagnostic_response.value.diagnostics
            else:
                report = _parse_diagnostic_report(
                    document.uri, diagnostic_response.value.result
                )
                if isinstance(report, Err):
                    return report
                diagnostics = report.value
        elif "not found" not in diagnostic_response.error.message.lower():
            return diagnostic_response

        for position in hover_positions:
            response: Result[_Response, LspError] = Err(
                LspError(LspErrorCode.SERVER, "hover request was not attempted")
            )
            for _ in range(3):
                sent = _request(
                    writer,
                    next_request_id,
                    "textDocument/hover",
                    {
                        "textDocument": {"uri": document.uri},
                        "position": _position_value(position),
                    },
                )
                if isinstance(sent, Err):
                    return sent
                response = _await_response(
                    process,
                    writer,
                    messages,
                    next_request_id,
                    deadline,
                    document.uri,
                )
                next_request_id += 1
                if not _is_mutation_cancellation(response):
                    break
            if isinstance(response, Err):
                return response
            if response.value.diagnostics is not None:
                diagnostics = response.value.diagnostics
            parsed_hover = _parse_hover(position, response.value.result)
            if isinstance(parsed_hover, Err):
                return parsed_hover
            hovers.append(parsed_hover.value)

        if diagnostics is None:
            published = _await_diagnostics(
                process,
                writer,
                messages,
                deadline,
                document.uri,
            )
            if isinstance(published, Err):
                return published
            diagnostics = published.value
        return Ok(LspAnalysis(diagnostics, tuple(hovers)))
    finally:
        _stop_server(process, writer, next_request_id, deadline)


@dataclass(frozen=True, slots=True)
class _Response:
    result: JsonValue
    diagnostics: tuple[LspDiagnostic, ...] | None


def _is_mutation_cancellation(
    response: Result[_Response, LspError],
) -> bool:
    return (
        isinstance(response, Err)
        and response.error.code is LspErrorCode.SERVER
        and "canceled due to subsequent mutation" in response.error.message.lower()
    )


def _await_response(
    process: subprocess.Popen[bytes],
    writer: BinaryIO,
    messages: queue.Queue[_IncomingMessage],
    request_id: int,
    deadline: float,
    document_uri: str,
) -> Result[_Response, LspError]:
    diagnostics: tuple[LspDiagnostic, ...] | None = None
    while True:
        received = _next_message(process, messages, deadline)
        if isinstance(received, Err):
            return received
        message = received.value
        published = _published_diagnostics(message, document_uri)
        if isinstance(published, Err):
            return published
        if published.value is not None:
            diagnostics = published.value
            continue
        if _is_server_request(message):
            answered = _answer_server_request(writer, message)
            if isinstance(answered, Err):
                return answered
            continue
        if _message_id(message) != request_id:
            continue
        error = message.get("error")
        if isinstance(error, dict):
            return Err(LspError(LspErrorCode.SERVER, _server_error_message(error)))
        return Ok(_Response(message.get("result"), diagnostics))


def _await_diagnostics(
    process: subprocess.Popen[bytes],
    writer: BinaryIO,
    messages: queue.Queue[_IncomingMessage],
    deadline: float,
    document_uri: str,
) -> Result[tuple[LspDiagnostic, ...], LspError]:
    while True:
        received = _next_message(process, messages, deadline)
        if isinstance(received, Err):
            return received
        message = received.value
        published = _published_diagnostics(message, document_uri)
        if isinstance(published, Err):
            return published
        if published.value is not None:
            return Ok(published.value)
        if _is_server_request(message):
            answered = _answer_server_request(writer, message)
            if isinstance(answered, Err):
                return answered


def _next_message(
    process: subprocess.Popen[bytes],
    messages: queue.Queue[_IncomingMessage],
    deadline: float,
) -> Result[dict[str, JsonValue], LspError]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return Err(LspError(LspErrorCode.TIMEOUT, "language server timed out"))
    try:
        incoming = messages.get(timeout=remaining)
    except queue.Empty:
        return Err(LspError(LspErrorCode.TIMEOUT, "language server timed out"))
    if incoming.error is not None:
        return Err(LspError(LspErrorCode.PROTOCOL, incoming.error))
    if incoming.value is None:
        return Err(
            LspError(
                LspErrorCode.EXIT,
                f"language server exited with status {process.poll()}",
            )
        )
    return Ok(incoming.value)


def _read_messages(stream: BinaryIO, messages: queue.Queue[_IncomingMessage]) -> None:
    while True:
        message = _read_message(stream)
        messages.put(message)
        if message.value is None:
            return


def _read_message(stream: BinaryIO) -> _IncomingMessage:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return _IncomingMessage(None)
        if line in {b"\r\n", b"\n"}:
            break
        try:
            name, value = line.decode("ascii").split(":", 1)
        except UnicodeDecodeError, ValueError:
            return _IncomingMessage(None, "invalid LSP header")
        headers[name.lower()] = value.strip()
    length_text = headers.get("content-length")
    if length_text is None:
        return _IncomingMessage(None, "missing Content-Length header")
    try:
        length = int(length_text)
    except ValueError:
        return _IncomingMessage(None, "invalid Content-Length header")
    payload = stream.read(length)
    if len(payload) != length:
        return _IncomingMessage(None, "truncated LSP message")
    try:
        decoded: object = json.loads(payload)
    except json.JSONDecodeError, UnicodeDecodeError:
        return _IncomingMessage(None, "invalid JSON-RPC payload")
    if not isinstance(decoded, dict):
        return _IncomingMessage(None, "JSON-RPC payload must be an object")
    untyped = cast(dict[object, object], decoded)
    if any(not isinstance(key, str) for key in untyped):
        return _IncomingMessage(None, "JSON-RPC payload must be an object")
    return _IncomingMessage(cast(dict[str, JsonValue], decoded))


def _write_message(
    writer: BinaryIO, message: Mapping[str, JsonValue]
) -> Result[None, LspError]:
    try:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        writer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        writer.write(payload)
        writer.flush()
    except OSError as error:
        return Err(LspError(LspErrorCode.EXIT, str(error)))
    return Ok(None)


def _request(
    writer: BinaryIO,
    request_id: int,
    method: str,
    parameters: Mapping[str, JsonValue],
) -> Result[None, LspError]:
    return _write_message(
        writer,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(parameters),
        },
    )


def _notify(
    writer: BinaryIO, method: str, parameters: Mapping[str, JsonValue]
) -> Result[None, LspError]:
    return _write_message(
        writer,
        {"jsonrpc": "2.0", "method": method, "params": dict(parameters)},
    )


def _initialize_parameters(
    configuration: LspConfiguration, document: LspDocument
) -> dict[str, JsonValue]:
    return {
        "processId": None,
        "rootUri": configuration.root.resolve().as_uri(),
        "capabilities": {
            "textDocument": {
                "publishDiagnostics": {"versionSupport": True},
                "hover": {"contentFormat": ["markdown", "plaintext"]},
            },
            "workspace": {"configuration": True},
        },
        "initializationOptions": dict(configuration.initialization_options or {}),
        "workspaceFolders": [
            {
                "uri": configuration.root.resolve().as_uri(),
                "name": configuration.root.name,
            }
        ],
        "clientInfo": {"name": "typeforge", "version": "0.1"},
        "trace": "off",
        "locale": "en",
    }


def _published_diagnostics(
    message: Mapping[str, JsonValue], document_uri: str
) -> Result[tuple[LspDiagnostic, ...] | None, LspError]:
    if message.get("method") != "textDocument/publishDiagnostics":
        return Ok(None)
    parameters = message.get("params")
    if not isinstance(parameters, dict) or parameters.get("uri") != document_uri:
        return Ok(None)
    values = parameters.get("diagnostics")
    if not isinstance(values, list):
        return Err(LspError(LspErrorCode.PROTOCOL, "invalid diagnostics payload"))
    diagnostics: list[LspDiagnostic] = []
    for value in values:
        parsed = _parse_diagnostic(document_uri, value)
        if isinstance(parsed, Err):
            return parsed
        diagnostics.append(parsed.value)
    return Ok(tuple(diagnostics))


def _parse_diagnostic(uri: str, value: JsonValue) -> Result[LspDiagnostic, LspError]:
    if not isinstance(value, dict):
        return Err(LspError(LspErrorCode.PROTOCOL, "invalid diagnostic"))
    parsed_range = _parse_range(value.get("range"))
    message = value.get("message")
    if isinstance(parsed_range, Err) or not isinstance(message, str):
        return Err(LspError(LspErrorCode.PROTOCOL, "invalid diagnostic"))
    severity = value.get("severity")
    code = value.get("code")
    source = value.get("source")
    return Ok(
        LspDiagnostic(
            uri,
            parsed_range.value,
            message,
            severity if isinstance(severity, int) else None,
            code if isinstance(code, str | int) else None,
            source if isinstance(source, str) else None,
        )
    )


def _parse_diagnostic_report(
    uri: str, value: JsonValue
) -> Result[tuple[LspDiagnostic, ...] | None, LspError]:
    if value is None:
        return Ok(None)
    if not isinstance(value, dict):
        return Err(LspError(LspErrorCode.PROTOCOL, "invalid diagnostic report"))
    items = value.get("items")
    if items is None:
        return Ok(None)
    if not isinstance(items, list):
        return Err(LspError(LspErrorCode.PROTOCOL, "invalid diagnostic report"))
    diagnostics: list[LspDiagnostic] = []
    for item in items:
        parsed = _parse_diagnostic(uri, item)
        if isinstance(parsed, Err):
            return parsed
        diagnostics.append(parsed.value)
    return Ok(tuple(diagnostics))


def _parse_hover(position: LspPosition, value: JsonValue) -> Result[LspHover, LspError]:
    if value is None:
        return Ok(LspHover(position, None))
    if not isinstance(value, dict):
        return Err(LspError(LspErrorCode.PROTOCOL, "invalid hover response"))
    contents = _hover_contents(value.get("contents"))
    if contents is None:
        return Err(LspError(LspErrorCode.PROTOCOL, "invalid hover contents"))
    range_value = value.get("range")
    if range_value is None:
        return Ok(LspHover(position, contents))
    parsed_range = _parse_range(range_value)
    if isinstance(parsed_range, Err):
        return parsed_range
    return Ok(LspHover(position, contents, parsed_range.value))


def _hover_contents(value: JsonValue) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("value")
        return text if isinstance(text, str) else None
    if isinstance(value, list):
        parts = tuple(_hover_contents(item) for item in value)
        if any(part is None for part in parts):
            return None
        return "\n\n".join(part for part in parts if part is not None)
    return None


def _parse_range(value: JsonValue) -> Result[LspRange, LspError]:
    if not isinstance(value, dict):
        return Err(LspError(LspErrorCode.PROTOCOL, "invalid range"))
    start = _parse_position(value.get("start"))
    end = _parse_position(value.get("end"))
    if start is None or end is None:
        return Err(LspError(LspErrorCode.PROTOCOL, "invalid range"))
    return Ok(LspRange(start, end))


def _parse_position(value: JsonValue) -> LspPosition | None:
    if not isinstance(value, dict):
        return None
    line = value.get("line")
    character = value.get("character")
    if not isinstance(line, int) or not isinstance(character, int):
        return None
    return LspPosition(line, character)


def _position_value(position: LspPosition) -> dict[str, JsonValue]:
    return {"line": position.line, "character": position.character}


def _is_server_request(message: Mapping[str, JsonValue]) -> bool:
    return isinstance(message.get("method"), str) and "id" in message


def _message_id(message: Mapping[str, JsonValue]) -> int | None:
    value = message.get("id")
    return value if isinstance(value, int) else None


def _answer_server_request(
    writer: BinaryIO, message: Mapping[str, JsonValue]
) -> Result[None, LspError]:
    request_id = message.get("id")
    method = message.get("method")
    if not isinstance(request_id, int | str) or not isinstance(method, str):
        return Err(LspError(LspErrorCode.PROTOCOL, "invalid server request"))
    result: JsonValue = None
    if method == "workspace/configuration":
        parameters = message.get("params")
        items: Sequence[JsonValue] = ()
        if isinstance(parameters, dict):
            candidate = parameters.get("items")
            if isinstance(candidate, list):
                items = candidate
        result = [None for _ in items]
    return _write_message(
        writer, {"jsonrpc": "2.0", "id": request_id, "result": result}
    )


def _server_error_message(error: Mapping[str, JsonValue]) -> str:
    message = error.get("message")
    return message if isinstance(message, str) else "language server request failed"


def _stop_server(
    process: subprocess.Popen[bytes],
    writer: BinaryIO,
    request_id: int,
    deadline: float,
) -> None:
    if process.poll() is not None:
        return
    _request(writer, request_id, "shutdown", {})
    _notify(writer, "exit", {})
    remaining = max(deadline - time.monotonic(), 0.0)
    try:
        process.wait(timeout=min(remaining, 1.0))
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
