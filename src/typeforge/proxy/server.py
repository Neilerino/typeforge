import queue
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from io import BufferedReader
from pathlib import Path
from typing import BinaryIO, Protocol, cast
from urllib.parse import unquote, urlparse

from typeforge._result import Err, Ok, Result
from typeforge.analysis.mapping import (
    generated_span_to_authored,
    mapping_for_generated_offset,
    position_from_offset,
)
from typeforge.analysis.model import (
    MappingKind,
    SourceMapping,
    SourcePosition,
    SourceSpan,
    VirtualDocument,
)
from typeforge.analysis.positions import source_position_from_utf16
from typeforge.diagnostics.render import render_return_check
from typeforge.documentation import DocumentationQuery
from typeforge.overlay import transform_source
from typeforge.proxy.framing import read_message, write_message
from typeforge.proxy.hover import append_hover_documentation
from typeforge.proxy.mapping import MappingDirection, map_message_payload
from typeforge.proxy.model import (
    DocumentState,
    JsonObject,
    JsonValue,
    PendingRequest,
    ProxyConfiguration,
    ProxyError,
    ProxyErrorCode,
    ProxyStreams,
    RequestId,
)
from typeforge.proxy.semantic_tokens import map_semantic_tokens


class _Peer(Enum):
    EDITOR = "editor"
    BACKEND = "backend"


class _BufferedBinaryReader(Protocol):
    @property
    def raw(self) -> BinaryIO: ...


@dataclass(frozen=True, slots=True)
class _Envelope:
    peer: _Peer
    message: JsonObject | None = None
    error: ProxyError | None = None


def run_proxy(
    streams: ProxyStreams, configuration: ProxyConfiguration
) -> Result[None, ProxyError]:
    try:
        backend = subprocess.Popen(
            configuration.backend_command,
            cwd=configuration.project_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
    except OSError as error:
        return Err(ProxyError(ProxyErrorCode.SPAWN, str(error)))
    if backend.stdin is None or backend.stdout is None:
        backend.kill()
        return Err(ProxyError(ProxyErrorCode.SPAWN, "backend pipes unavailable"))
    backend_input = cast(BinaryIO, backend.stdout)
    backend_output = cast(BinaryIO, backend.stdin)
    incoming: queue.Queue[_Envelope] = queue.Queue()
    readers = (
        _start_reader(streams.editor_input, _Peer.EDITOR, incoming),
        _start_reader(backend_input, _Peer.BACKEND, incoming),
    )
    documents: dict[str, DocumentState] = {}
    pending: dict[RequestId, PendingRequest] = {}
    editor_exited = False
    try:
        while True:
            envelope = incoming.get()
            if envelope.error is not None:
                return Err(envelope.error)
            if envelope.message is None:
                if envelope.peer is _Peer.EDITOR:
                    return Ok(None)
                if editor_exited:
                    return Ok(None)
                return Err(
                    ProxyError(
                        ProxyErrorCode.BACKEND_EXIT,
                        f"backend exited with status {backend.poll()}",
                    )
                )
            if envelope.peer is _Peer.EDITOR:
                handled = _handle_editor_message(
                    envelope.message,
                    backend_output,
                    configuration,
                    documents,
                    pending,
                )
                if isinstance(handled, Err):
                    return handled
                editor_exited = envelope.message.get("method") == "exit"
                if editor_exited:
                    return Ok(None)
            else:
                handled = _handle_backend_message(
                    envelope.message,
                    streams.editor_output,
                    configuration,
                    documents,
                    pending,
                )
                if isinstance(handled, Err):
                    return handled
    finally:
        _stop_backend(backend, backend_output)
        for reader in readers:
            reader.join(timeout=0.1)


def _start_reader(
    stream: BinaryIO, peer: _Peer, incoming: queue.Queue[_Envelope]
) -> threading.Thread:
    reader = stream
    if isinstance(stream, BufferedReader):
        reader = cast(_BufferedBinaryReader, stream).raw
    thread = threading.Thread(
        target=_read_loop,
        args=(reader, peer, incoming),
        daemon=True,
    )
    thread.start()
    return thread


def _read_loop(stream: BinaryIO, peer: _Peer, incoming: queue.Queue[_Envelope]) -> None:
    while True:
        result = read_message(stream)
        if isinstance(result, Err):
            incoming.put(_Envelope(peer, error=result.error))
            return
        incoming.put(_Envelope(peer, message=result.value))
        if result.value is None:
            return


def _handle_editor_message(
    message: JsonObject,
    backend_output: BinaryIO,
    configuration: ProxyConfiguration,
    documents: dict[str, DocumentState],
    pending: dict[RequestId, PendingRequest],
) -> Result[None, ProxyError]:
    method = message.get("method")
    transformed = message
    if method == "initialize":
        transformed = configuration.initialize(message)
    elif method == "textDocument/didOpen":
        opened = _open_document(message, configuration)
        if isinstance(opened, Err):
            return opened
        uri, state, transformed = opened.value
        documents[uri] = state
    elif method == "textDocument/didChange":
        changed = _change_document(message, configuration, documents)
        if isinstance(changed, Err):
            return changed
        uri, state, transformed = changed.value
        documents[uri] = state
    elif method == "textDocument/didClose":
        closed_uri = _text_document_uri(message)
        if closed_uri is not None:
            documents.pop(closed_uri, None)
    elif isinstance(method, str):
        mapped = map_message_payload(
            message,
            documents,
            MappingDirection.AUTHORED_TO_GENERATED,
            _text_document_uri(message),
        )
        if isinstance(mapped, dict):
            transformed = mapped

    request_id = _request_id(message)
    if request_id is not None and isinstance(method, str):
        request_uri = _text_document_uri(message)
        pending[request_id] = PendingRequest(
            method,
            request_uri,
            _authored_request_position(message, request_uri, documents),
        )
    return write_message(backend_output, transformed)


def _handle_backend_message(
    message: JsonObject,
    editor_output: BinaryIO,
    configuration: ProxyConfiguration,
    documents: dict[str, DocumentState],
    pending: dict[RequestId, PendingRequest],
) -> Result[None, ProxyError]:
    method = message.get("method")
    transformed = message
    if method == "textDocument/publishDiagnostics":
        transformed = _map_diagnostics(message, configuration, documents)
    elif isinstance(method, str):
        mapped = map_message_payload(
            message,
            documents,
            MappingDirection.GENERATED_TO_AUTHORED,
            _text_document_uri(message),
        )
        if isinstance(mapped, dict):
            transformed = mapped
    request_id = _request_id(message)
    if request_id is not None and "method" not in message:
        request = pending.pop(request_id, None)
        if request is not None and request.method == "initialize":
            transformed = _map_capabilities(message)
        elif request is not None and request.method == "textDocument/diagnostic":
            transformed = _map_diagnostic_response(
                message, request, configuration, documents
            )
        elif request is not None and request.method.startswith(
            "textDocument/semanticTokens/"
        ):
            transformed = _map_semantic_token_response(message, request, documents)
        elif request is not None:
            mapped = map_message_payload(
                message,
                documents,
                MappingDirection.GENERATED_TO_AUTHORED,
                request.uri,
            )
            if isinstance(mapped, dict):
                transformed = mapped
            if request.method == "textDocument/hover":
                transformed = _add_hover_documentation(
                    transformed,
                    request,
                    configuration,
                    documents,
                )
    return write_message(editor_output, transformed)


def _add_hover_documentation(
    message: JsonObject,
    request: PendingRequest,
    configuration: ProxyConfiguration,
    documents: dict[str, DocumentState],
) -> JsonObject:
    state = documents.get(request.uri) if request.uri is not None else None
    if state is None or request.position is None:
        return message
    query = DocumentationQuery(
        document=state.document,
        position=request.position,
        project_root=configuration.project_root,
        source_roots=configuration.source_roots,
        workspace_documents=tuple(
            documents[uri].document for uri in sorted(documents) if uri != request.uri
        ),
    )
    documentation = configuration.documentation(query)
    if isinstance(documentation, Err) or documentation.value is None:
        return message
    return append_hover_documentation(message, documentation.value.markdown)


def _map_capabilities(message: JsonObject) -> JsonObject:
    result = _object(message.get("result"))
    capabilities = _object(result.get("capabilities")) if result else None
    if result is None or capabilities is None:
        return message
    semantic = _object(capabilities.get("semanticTokensProvider"))
    completion = _object(capabilities.get("completionProvider"))
    mapped = dict(capabilities)
    if semantic is not None:
        mapped["semanticTokensProvider"] = {**semantic, "full": True}
    if completion is not None:
        mapped["completionProvider"] = {**completion, "resolveProvider": False}
    mapped.pop("notebookDocumentSync", None)
    return {**message, "result": {**result, "capabilities": mapped}}


def _map_semantic_token_response(
    message: JsonObject,
    request: PendingRequest,
    documents: dict[str, DocumentState],
) -> JsonObject:
    state = documents.get(request.uri) if request.uri is not None else None
    result = _object(message.get("result"))
    data = result.get("data") if result is not None else None
    if (
        state is None
        or result is None
        or not isinstance(data, list)
        or not all(isinstance(item, int) for item in data)
    ):
        return message
    return {
        **message,
        "result": {
            **result,
            "data": cast(
                list[JsonValue],
                map_semantic_tokens(cast(list[int], data), state.document),
            ),
        },
    }


def _open_document(
    message: JsonObject, configuration: ProxyConfiguration
) -> Result[tuple[str, DocumentState, JsonObject], ProxyError]:
    parameters = _object(message.get("params"))
    text_document = _object(parameters.get("textDocument")) if parameters else None
    if parameters is None or text_document is None:
        return Err(_protocol_error("didOpen requires textDocument"))
    uri = text_document.get("uri")
    text = text_document.get("text")
    version = text_document.get("version")
    if not isinstance(uri, str) or not isinstance(text, str):
        return Err(_protocol_error("didOpen requires uri and text"))
    transformed = _transform(
        uri,
        text,
        version if isinstance(version, int) else 0,
        configuration,
    )
    if isinstance(transformed, Err):
        return transformed
    forwarded: JsonObject = {
        **message,
        "params": {
            **parameters,
            "textDocument": {
                **text_document,
                "text": transformed.value.generated_text,
            },
        },
    }
    return Ok((uri, DocumentState(transformed.value), forwarded))


def _change_document(
    message: JsonObject,
    configuration: ProxyConfiguration,
    documents: dict[str, DocumentState],
) -> Result[tuple[str, DocumentState, JsonObject], ProxyError]:
    parameters = _object(message.get("params"))
    text_document = _object(parameters.get("textDocument")) if parameters else None
    changes = parameters.get("contentChanges") if parameters else None
    if parameters is None or text_document is None or not isinstance(changes, list):
        return Err(_protocol_error("didChange requires document and changes"))
    uri = text_document.get("uri")
    version = text_document.get("version")
    if not isinstance(uri, str) or uri not in documents:
        return Err(_protocol_error("didChange references an unopened document"))
    authored = _apply_changes(documents[uri].document.authored_text, changes)
    if isinstance(authored, Err):
        return authored
    transformed = _transform(
        uri,
        authored.value,
        version if isinstance(version, int) else documents[uri].document.version + 1,
        configuration,
    )
    if isinstance(transformed, Err):
        return transformed
    forwarded: JsonObject = {
        **message,
        "params": {
            **parameters,
            "contentChanges": [{"text": transformed.value.generated_text}],
        },
    }
    return Ok((uri, DocumentState(transformed.value), forwarded))


def _apply_changes(source: str, changes: list[JsonValue]) -> Result[str, ProxyError]:
    current = source
    for change_value in changes:
        change = _object(change_value)
        if change is None:
            return Err(_protocol_error("invalid content change"))
        replacement = change.get("text")
        if not isinstance(replacement, str):
            return Err(_protocol_error("invalid content change"))
        range_value = _object(change.get("range"))
        if range_value is None:
            current = replacement
            continue
        span = _source_span(current, range_value)
        if span is None:
            return Err(_protocol_error("invalid content change range"))
        current = (
            current[: span.start.offset] + replacement + current[span.end.offset :]
        )
    return Ok(current)


def _map_diagnostics(
    message: JsonObject,
    configuration: ProxyConfiguration,
    documents: dict[str, DocumentState],
) -> JsonObject:
    parameters = _object(message.get("params"))
    if parameters is None:
        return message
    uri = parameters.get("uri")
    values = parameters.get("diagnostics")
    state = documents.get(uri) if isinstance(uri, str) else None
    if state is None or not isinstance(values, list):
        return message
    mapped = _map_diagnostic_values(values, state.document, configuration)
    return {**message, "params": {**parameters, "diagnostics": mapped}}


def _map_diagnostic_response(
    message: JsonObject,
    request: PendingRequest,
    configuration: ProxyConfiguration,
    documents: dict[str, DocumentState],
) -> JsonObject:
    state = documents.get(request.uri) if request.uri is not None else None
    result = _object(message.get("result"))
    values = result.get("items") if result is not None else None
    if state is None or result is None or not isinstance(values, list):
        return message
    return {
        **message,
        "result": {
            **result,
            "items": _map_diagnostic_values(values, state.document, configuration),
        },
    }


def _map_diagnostic_values(
    values: list[JsonValue],
    document: VirtualDocument,
    configuration: ProxyConfiguration,
) -> list[JsonValue]:
    mapped: list[JsonValue] = []
    verified_offsets = _verification_diagnostic_offsets(values, document)
    for value in values:
        diagnostic = _object(value)
        range_value = _object(diagnostic.get("range")) if diagnostic else None
        if diagnostic is None or range_value is None:
            mapped.append(value)
            continue
        generated = _source_span(document.generated_text, range_value)
        if generated is None:
            mapped.append(value)
            continue
        authored = generated_span_to_authored(document, generated)
        mapping = mapping_for_generated_offset(
            document.mappings, generated.start.offset
        )
        provenance = mapping.provenance if mapping is not None else None
        if (
            provenance is None
            and diagnostic.get("code") == "bad-return"
            and authored.start.offset in verified_offsets
        ):
            continue
        if configuration.suppress_diagnostic(diagnostic, document, authored):
            continue
        presented = configuration.present_diagnostic(diagnostic, document, authored)
        message = presented.get("message")
        if provenance is not None and isinstance(message, str):
            presented = {
                **presented,
                "message": render_return_check(provenance, message),
            }
        normalized = map_message_payload(
            presented,
            {document.uri: DocumentState(document)},
            MappingDirection.GENERATED_TO_AUTHORED,
            document.uri,
        )
        mapped.append(normalized)
    return mapped


def _verification_diagnostic_offsets(
    values: list[JsonValue], document: VirtualDocument
) -> frozenset[int]:
    offsets: set[int] = set()
    for value in values:
        diagnostic = _object(value)
        range_value = _object(diagnostic.get("range")) if diagnostic else None
        if range_value is None:
            continue
        generated = _source_span(document.generated_text, range_value)
        if generated is None:
            continue
        mapping = mapping_for_generated_offset(
            document.mappings, generated.start.offset
        )
        if mapping is not None and mapping.provenance is not None:
            offsets.add(mapping.authored.start.offset)
    return frozenset(offsets)


def _transform(
    uri: str,
    source: str,
    version: int,
    configuration: ProxyConfiguration,
) -> Result[VirtualDocument, ProxyError]:
    path = _uri_path(uri)
    if path is None:
        return Ok(_identity_document(uri, Path(uri), source, version))
    transformed = transform_source(
        source,
        path,
        maximum_arity=configuration.maximum_arity,
        version=version,
    )
    if isinstance(transformed, Err):
        return Ok(_identity_document(uri, path, source, version))
    return transformed


def _identity_document(
    uri: str,
    path: Path,
    source: str,
    version: int,
) -> VirtualDocument:
    start = position_from_offset(source, 0)
    end = position_from_offset(source, len(source))
    span = SourceSpan(start, end)
    return VirtualDocument(
        uri=uri,
        path=path,
        version=version,
        authored_text=source,
        generated_text=source,
        mappings=(SourceMapping(span, span, MappingKind.AUTHORED),),
    )


def _source_span(source: str, value: JsonObject) -> SourceSpan | None:
    start = _object(value.get("start"))
    end = _object(value.get("end"))
    if start is None or end is None:
        return None
    start_position = _source_position(source, start)
    end_position = _source_position(source, end)
    if start_position is None or end_position is None:
        return None
    return SourceSpan(start_position, end_position)


def _source_position(source: str, value: JsonObject) -> SourcePosition | None:
    line = value.get("line")
    character = value.get("character")
    if not isinstance(line, int) or not isinstance(character, int) or line < 0:
        return None
    return source_position_from_utf16(source, line, character)


def _text_document_uri(message: JsonObject) -> str | None:
    parameters = _object(message.get("params"))
    text_document = _object(parameters.get("textDocument")) if parameters else None
    uri = text_document.get("uri") if text_document else None
    return uri if isinstance(uri, str) else None


def _authored_request_position(
    message: JsonObject,
    uri: str | None,
    documents: dict[str, DocumentState],
) -> SourcePosition | None:
    state = documents.get(uri) if uri is not None else None
    parameters = _object(message.get("params"))
    position = _object(parameters.get("position")) if parameters is not None else None
    if state is None or position is None:
        return None
    return _source_position(state.document.authored_text, position)


def _request_id(message: JsonObject) -> RequestId | None:
    value = message.get("id")
    return value if isinstance(value, int | str) else None


def _object(value: JsonValue) -> JsonObject | None:
    return value if isinstance(value, dict) else None


def _uri_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path))


def _protocol_error(message: str) -> ProxyError:
    return ProxyError(ProxyErrorCode.PROTOCOL, message)


def _stop_backend(backend: subprocess.Popen[bytes], backend_output: BinaryIO) -> None:
    if backend.poll() is not None:
        return
    try:
        backend_output.close()
        backend.wait(timeout=1.0)
    except OSError, subprocess.TimeoutExpired:
        backend.terminate()
        try:
            backend.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            backend.kill()
