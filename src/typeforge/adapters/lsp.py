from __future__ import annotations

import queue
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from typing import BinaryIO, cast

from returns.result import Failure, Result, Success, safe

from pydantic import ValidationError
from typeforge.adapters.lsp_model import (
    DiagnosticReport,
    HoverResultPayload,
    LspAnalysis,
    LspConfiguration,
    LspDiagnostic,
    LspDocument,
    LspError,
    LspErrorCode,
    LspExitError,
    LspHover,
    LspPosition,
    LspProtocolError,
    LspRange,
    LspServerError,
    LspSpawnError,
    LspTimeoutError,
    PublishedDiagnostics,
    Response,
)
from typeforge.utils.stream import (
    JsonObject,
    JsonValue,
    LspStreamError,
    read_lsp_message,
    write_lsp_message,
)

__all__ = (
    "LspAnalysis",
    "LspConfiguration",
    "LspDiagnostic",
    "LspDocument",
    "LspError",
    "LspErrorCode",
    "LspExitError",
    "LspHover",
    "LspPosition",
    "LspProtocolError",
    "LspRange",
    "LspServerError",
    "LspSpawnError",
    "LspTimeoutError",
    "analyze_document",
)

type QueueMessage = Result[JsonObject | None, LspStreamError]


@safe(exceptions=(LspError,))
def analyze_document(
    configuration: LspConfiguration,
    document: LspDocument,
    hover_positions: tuple[LspPosition, ...] = (),
) -> LspAnalysis:
    try:
        process = subprocess.Popen(
            configuration.command,
            cwd=configuration.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise LspSpawnError(str(error)) from error
    if process.stdin is None or process.stdout is None:
        process.kill()
        raise LspSpawnError("language server pipes unavailable")
    writer = cast(BinaryIO, process.stdin)
    reader_stream = cast(BinaryIO, process.stdout)

    messages: queue.Queue[QueueMessage] = queue.Queue()
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
        if isinstance(initialize, Failure):
            raise initialize.failure()
        initialized = _await_response(
            process,
            writer,
            messages,
            next_request_id,
            deadline,
            document.uri,
        )
        if isinstance(initialized, Failure):
            raise initialized.failure()
        next_request_id += 1
        notified = _notify(writer, "initialized", {})
        if isinstance(notified, Failure):
            raise notified.failure()
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
        if isinstance(opened, Failure):
            raise opened.failure()

        diagnostic_response: Result[Response, LspError] = Failure(
            LspServerError("diagnostic request was not attempted")
        )
        for _ in range(3):
            pulled = _request(
                writer,
                next_request_id,
                "textDocument/diagnostic",
                {"textDocument": {"uri": document.uri}},
            )
            if isinstance(pulled, Failure):
                raise pulled.failure()
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
        if isinstance(diagnostic_response, Success):
            if diagnostic_response.unwrap().diagnostics is not None:
                diagnostics = diagnostic_response.unwrap().diagnostics
            else:
                report = _parse_diagnostic_report(diagnostic_response.unwrap().result)
                if isinstance(report, Failure):
                    raise report.failure()
                diagnostics = report.unwrap()
        elif "not found" not in diagnostic_response.failure().message.lower():
            raise diagnostic_response.failure()

        for position in hover_positions:
            response: Result[Response, LspError] = Failure(
                LspServerError("hover request was not attempted")
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
                if isinstance(sent, Failure):
                    raise sent.failure()
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
            if isinstance(response, Failure):
                raise response.failure()
            if response.unwrap().diagnostics is not None:
                diagnostics = response.unwrap().diagnostics
            parsed_hover = _parse_hover(position, response.unwrap().result)
            if isinstance(parsed_hover, Failure):
                raise parsed_hover.failure()
            hovers.append(parsed_hover.unwrap())

        if diagnostics is None:
            published = _await_diagnostics(
                process,
                writer,
                messages,
                deadline,
                document.uri,
            )
            if isinstance(published, Failure):
                raise published.failure()
            diagnostics = published.unwrap()
        return LspAnalysis(diagnostics, tuple(hovers))
    finally:
        _stop_server(process, writer, next_request_id, deadline)


def _is_mutation_cancellation(
    response: Result[Response, LspError],
) -> bool:
    return (
        isinstance(response, Failure)
        and isinstance(response.failure(), LspServerError)
        and "canceled due to subsequent mutation" in response.failure().message.lower()
    )


def _await_response(
    process: subprocess.Popen[bytes],
    writer: BinaryIO,
    messages: queue.Queue[QueueMessage],
    request_id: int,
    deadline: float,
    document_uri: str,
) -> Result[Response, LspError]:
    diagnostics: tuple[LspDiagnostic, ...] | None = None
    while True:
        received = _next_message(process, messages, deadline)
        if isinstance(received, Failure):
            return received
        message = received.unwrap()
        published = _published_diagnostics(message, document_uri)
        if isinstance(published, Failure):
            return published
        if published.unwrap() is not None:
            diagnostics = published.unwrap()
            continue
        if _is_server_request(message):
            answered = _answer_server_request(writer, message)
            if isinstance(answered, Failure):
                return answered
            continue
        if _message_id(message) != request_id:
            continue
        error = message.get("error")
        if isinstance(error, dict):
            return Failure(LspServerError(_server_error_message(error)))
        return Success(Response(message.get("result"), diagnostics))


def _await_diagnostics(
    process: subprocess.Popen[bytes],
    writer: BinaryIO,
    messages: queue.Queue[QueueMessage],
    deadline: float,
    document_uri: str,
) -> Result[tuple[LspDiagnostic, ...], LspError]:
    while True:
        received = _next_message(process, messages, deadline)
        if isinstance(received, Failure):
            return received
        message = received.unwrap()
        published = _published_diagnostics(message, document_uri)
        if isinstance(published, Failure):
            return published
        published_diagnostics = published.unwrap()
        if published_diagnostics is not None:
            return Success(published_diagnostics)
        if _is_server_request(message):
            answered = _answer_server_request(writer, message)
            if isinstance(answered, Failure):
                return answered


def _next_message(
    process: subprocess.Popen[bytes],
    messages: queue.Queue[QueueMessage],
    deadline: float,
) -> Result[JsonObject, LspError]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return Failure(LspTimeoutError("language server timed out"))
    try:
        incoming = messages.get(timeout=remaining)
    except queue.Empty:
        return Failure(LspTimeoutError("language server timed out"))
    if isinstance(incoming, Failure):
        return Failure(LspProtocolError(incoming.failure().message))
    message = incoming.unwrap()
    if message is None:
        return Failure(
            LspExitError(f"language server exited with status {process.poll()}")
        )
    return Success(message)


def _read_messages(stream: BinaryIO, messages: queue.Queue[QueueMessage]) -> None:
    while True:
        received = read_lsp_message(stream)
        messages.put(received)
        if isinstance(received, Failure) or received.unwrap() is None:
            return


def _write_message(
    writer: BinaryIO, message: Mapping[str, JsonValue]
) -> Result[None, LspError]:
    return write_lsp_message(writer, message).alt(
        lambda error: LspExitError(error.message)
    )


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


@safe(exceptions=(LspError,))
def _published_diagnostics(
    message: JsonObject, document_uri: str
) -> tuple[LspDiagnostic, ...] | None:
    if message.get("method") != "textDocument/publishDiagnostics":
        return None
    try:
        parsed = PublishedDiagnostics.model_validate(message)
    except ValidationError as error:
        raise LspProtocolError("invalid publishDiagnostics message") from error

    if parsed.params.uri != document_uri:
        return None
    return tuple(parsed.params.diagnostics)


@safe(exceptions=(LspError,))
def _parse_diagnostic_report(
    value: JsonValue,
) -> tuple[LspDiagnostic, ...] | None:
    if value is None:
        return None
    try:
        report = DiagnosticReport.model_validate(value)
    except ValidationError as error:
        raise LspProtocolError("invalid diagnostic report") from error
    if report.items is None:
        return None
    return tuple(report.items)


@safe(exceptions=(LspError,))
def _parse_hover(position: LspPosition, value: JsonValue) -> LspHover:
    if value is None:
        return LspHover(position, None)
    try:
        hover = HoverResultPayload.model_validate(value)
    except ValidationError as error:
        raise LspProtocolError("invalid hover response") from error
    contents = _hover_contents(hover.contents)
    if contents is None:
        raise LspProtocolError("invalid hover contents")
    if hover.range is None:
        return LspHover(position, contents)
    return LspHover(position, contents, hover.range)


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
        return Failure(LspProtocolError("invalid server request"))
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
