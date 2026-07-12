import os
import sys
import threading
from pathlib import Path
from typing import BinaryIO, cast

from typeforge._result import Ok, Result
from typeforge.proxy import (
    ProxyError,
    ProxyStreams,
    pyrefly_proxy_configuration,
    run_proxy,
)
from typeforge.proxy.framing import read_message, write_message
from typeforge.proxy.model import JsonObject, JsonValue

FAKE_BACKEND = r"""
import json
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if line in {b"\r\n", b"\n"}:
            break
        name, value = line.decode("ascii").split(":", 1)
        headers[name.lower()] = value.strip()
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])))


def write_message(message):
    payload = json.dumps(message, separators=(",", ":")).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode())
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def position(text, needle):
    offset = text.index(needle)
    prefix = text[:offset]
    line = prefix[prefix.rfind("\n") + 1:]
    return {"line": prefix.count("\n"), "character": len(line.encode("utf-16-le")) // 2}


initialize = read_message()
options = initialize["params"]["initializationOptions"]
assert options["pythonPath"]
assert options["pyrefly"]["typeCheckingMode"] == "strict"
write_message({
    "jsonrpc": "2.0",
    "id": initialize["id"],
    "result": {"capabilities": {
        "completionProvider": {
            "triggerCharacters": ["."],
            "resolveProvider": True,
        },
        "definitionProvider": True,
        "hoverProvider": True,
        "semanticTokensProvider": {
            "legend": {"tokenTypes": ["variable"], "tokenModifiers": []},
            "full": {"delta": True},
        },
        "textDocumentSync": 2,
    }},
})
assert read_message()["method"] == "initialized"

opened = read_message()
assert opened["method"] == "textDocument/didOpen"
opened_document = opened["params"]["textDocument"]
generated = opened_document["text"]
assert "# typeforge: overlay" in generated
result_position = position(generated, "result =")
result_end = {**result_position, "character": result_position["character"] + 6}
marker_position = position(generated, "Collect")
marker_end = {**marker_position, "character": marker_position["character"] + 7}
write_message({
    "jsonrpc": "2.0",
    "method": "textDocument/publishDiagnostics",
    "params": {
        "uri": opened_document["uri"],
        "version": opened_document["version"],
        "diagnostics": [{
            "range": {"start": result_position, "end": result_end},
            "severity": 1,
            "code": "fake-error",
            "message": "fake diagnostic",
        }, {
            "range": {"start": marker_position, "end": marker_end},
            "severity": 4,
            "code": "unused-import",
            "message": "Import `Collect` is not accessed",
        }],
    },
})

hover = read_message()
assert hover["method"] == "textDocument/hover"
assert hover["params"]["position"] == result_position
write_message({
    "jsonrpc": "2.0",
    "id": hover["id"],
    "result": {
        "contents": {"kind": "markdown", "value": "```python\ntuple[int]\n```"},
        "range": {"start": result_position, "end": result_end},
    },
})

completion = read_message()
assert completion["method"] == "textDocument/completion"
assert completion["params"]["position"] == result_position
write_message({
    "jsonrpc": "2.0",
    "id": completion["id"],
    "result": {
        "isIncomplete": False,
        "items": [{
            "label": "result",
            "textEdit": {
                "range": {"start": result_position, "end": result_end},
                "newText": "result",
            },
        }],
    },
})

semantic = read_message()
assert semantic["method"] == "textDocument/semanticTokens/full"
overlay_position = position(generated, "values_1")
result_delta_line = result_position["line"] - overlay_position["line"]
result_delta_character = (
    result_position["character"]
    if result_delta_line
    else result_position["character"] - overlay_position["character"]
)
write_message({
    "jsonrpc": "2.0",
    "id": semantic["id"],
    "result": {"data": [
        overlay_position["line"], overlay_position["character"], 8, 0, 0,
        result_delta_line, result_delta_character, 6, 0, 0,
    ]},
})

invalid = read_message()
assert invalid["method"] == "textDocument/didChange"
changes = invalid["params"]["contentChanges"]
assert len(changes) == 1 and "range" not in changes[0]
assert 'result = collect(' in changes[0]["text"]
assert "# typeforge: overlay" not in changes[0]["text"]

recovered = read_message()
assert recovered["method"] == "textDocument/didChange"
changes = recovered["params"]["contentChanges"]
assert len(changes) == 1 and "range" not in changes[0]
assert 'collect("two")' in changes[0]["text"]
assert "# typeforge: overlay" in changes[0]["text"]

assert read_message()["method"] == "textDocument/didClose"
shutdown = read_message()
assert shutdown["method"] == "shutdown"
write_message({"jsonrpc": "2.0", "id": shutdown["id"], "result": None})
assert read_message()["method"] == "exit"
""".lstrip()


def pipe() -> tuple[BinaryIO, BinaryIO]:
    reader, writer = os.pipe()
    return (
        cast(BinaryIO, os.fdopen(reader, "rb", buffering=0)),
        cast(BinaryIO, os.fdopen(writer, "wb", buffering=0)),
    )


def receive(stream: BinaryIO) -> JsonObject:
    received = read_message(stream)
    assert isinstance(received, Ok)
    assert received.value is not None
    return received.value


def send(stream: BinaryIO, message: JsonObject) -> None:
    assert isinstance(write_message(stream, message), Ok)


def response_for(
    editor_input: BinaryIO,
    editor_output: BinaryIO,
    request_id: int,
) -> JsonObject:
    while True:
        message = receive(editor_input)
        method = message.get("method")
        server_id = message.get("id")
        if isinstance(method, str) and isinstance(server_id, int | str):
            parameters = message.get("params")
            items: list[JsonValue] = []
            if isinstance(parameters, dict):
                candidate = parameters.get("items")
                if isinstance(candidate, list):
                    items = candidate
            result: JsonValue = [None for _ in items] if items else None
            send(
                editor_output,
                {"jsonrpc": "2.0", "id": server_id, "result": result},
            )
            continue
        if server_id == request_id:
            return message


def test_proxy_forwards_lifecycle_and_maps_documents(tmp_path: Path) -> None:
    backend = tmp_path / "fake_backend.py"
    backend.write_text(FAKE_BACKEND, encoding="utf-8")
    proxy_input, editor_output = pipe()
    editor_input, proxy_output = pipe()
    completed: list[Result[None, ProxyError]] = []
    proxy_thread = threading.Thread(
        target=lambda: completed.append(
            run_proxy(
                ProxyStreams(proxy_input, proxy_output),
                pyrefly_proxy_configuration(
                    project_root=tmp_path,
                    backend_command=(sys.executable, str(backend)),
                    maximum_arity=1,
                ),
            )
        )
    )
    proxy_thread.start()
    path = tmp_path / "example.py"
    uri = path.as_uri()
    source = (
        "from typeforge import Collect, Each\n"
        "def collect[T](*values: Each[T]) -> Collect[T]:\n"
        "    return values\n"
        'emoji = "😀"; result = collect(1)\n'
    )

    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"rootUri": tmp_path.as_uri(), "capabilities": {}},
        },
    )
    initialized = receive(editor_input)
    assert initialized["id"] == 1
    initialized_result = initialized["result"]
    assert isinstance(initialized_result, dict)
    assert initialized_result["capabilities"] == {
        "completionProvider": {
            "triggerCharacters": ["."],
            "resolveProvider": False,
        },
        "definitionProvider": True,
        "hoverProvider": True,
        "semanticTokensProvider": {
            "legend": {"tokenTypes": ["variable"], "tokenModifiers": []},
            "full": True,
        },
        "textDocumentSync": 2,
    }
    send(editor_output, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "python",
                    "version": 1,
                    "text": source,
                }
            },
        },
    )
    diagnostics = receive(editor_input)
    diagnostic_range = diagnostics["params"]
    assert isinstance(diagnostic_range, dict)
    diagnostic_values = diagnostic_range["diagnostics"]
    assert isinstance(diagnostic_values, list)
    assert len(diagnostic_values) == 1
    diagnostic = diagnostic_values[0]
    assert isinstance(diagnostic, dict)
    assert diagnostic["range"] == {
        "start": {"line": 3, "character": 14},
        "end": {"line": 3, "character": 20},
    }
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 3, "character": 14},
            },
        },
    )
    hover = receive(editor_input)
    result = hover["result"]
    assert isinstance(result, dict)
    assert result["range"] == {
        "start": {"line": 3, "character": 14},
        "end": {"line": 3, "character": 20},
    }
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 3, "character": 14},
            },
        },
    )
    completion = receive(editor_input)
    completion_result = completion["result"]
    assert isinstance(completion_result, dict)
    completion_items = completion_result["items"]
    assert isinstance(completion_items, list)
    completion_item = completion_items[0]
    assert isinstance(completion_item, dict)
    text_edit = completion_item["textEdit"]
    assert isinstance(text_edit, dict)
    assert text_edit["range"] == {
        "start": {"line": 3, "character": 14},
        "end": {"line": 3, "character": 20},
    }
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "textDocument/semanticTokens/full",
            "params": {"textDocument": {"uri": uri}},
        },
    )
    semantic = receive(editor_input)
    semantic_result = semantic["result"]
    assert isinstance(semantic_result, dict)
    assert semantic_result["data"] == [3, 14, 6, 0, 0]
    invalid_source = source.replace("collect(1)", "collect(")
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {
                "textDocument": {"uri": uri, "version": 2},
                "contentChanges": [{"text": invalid_source}],
            },
        },
    )
    recovered_source = source.replace("collect(1)", 'collect("two")')
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {
                "textDocument": {"uri": uri, "version": 3},
                "contentChanges": [{"text": recovered_source}],
            },
        },
    )
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didClose",
            "params": {"textDocument": {"uri": uri}},
        },
    )
    send(editor_output, {"jsonrpc": "2.0", "id": 5, "method": "shutdown"})
    assert receive(editor_input)["id"] == 5
    send(editor_output, {"jsonrpc": "2.0", "method": "exit"})
    proxy_thread.join(timeout=5.0)

    assert not proxy_thread.is_alive()
    assert completed == [Ok(None)]


def test_real_pyrefly_proxy_hovers_same_file_ecs_result(tmp_path: Path) -> None:
    documented_types = tmp_path / "documented_types.py"
    documented_types.write_text(
        "from typing import Annotated\n"
        "from typeforge import Doc\n"
        'type EntityId = Annotated[int, Doc("An entity identifier.")]\n',
        encoding="utf-8",
    )
    source = """
from typing import Protocol, assert_type

from documented_types import EntityId
from typeforge import Case, Collect, Default, Each, Map, Value


class Component(Protocol):
    def __hash__(self) -> int: ...


class Option[T: Component](Protocol):
    value: T


type QueryResult[T] = Map[
    T,
    Case[Option[Value], Value | None],
    Default[T],
]


class World[E]:
    def query[T](
        self,
        *components: Each[type[T]],
    ) -> tuple[E, *Collect[QueryResult[T]]] | None:
        raise NotImplementedError


class Position:
    pass


class Velocity:
    pass


world = World[int]()
entity_id: EntityId = 1
result_1 = world.query(Position, Velocity)
assert_type(result_1, tuple[int, Position, Velocity] | None)
result_2 = world.query(Position, Option[Velocity])
assert_type(result_2, tuple[int, Position, Velocity | None] | None)
""".lstrip()
    path = tmp_path / "ecs.py"
    path.write_text(source, encoding="utf-8")
    proxy_input, editor_output = pipe()
    editor_input, proxy_output = pipe()
    completed: list[Result[None, ProxyError]] = []
    pyrefly = Path(sys.executable).with_name("pyrefly")
    proxy_thread = threading.Thread(
        target=lambda: completed.append(
            run_proxy(
                ProxyStreams(proxy_input, proxy_output),
                pyrefly_proxy_configuration(
                    project_root=tmp_path,
                    backend_command=(str(pyrefly), "lsp"),
                    maximum_arity=2,
                ),
            )
        )
    )
    proxy_thread.start()
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "rootUri": tmp_path.as_uri(),
                "capabilities": {},
            },
        },
    )
    initialized = response_for(editor_input, editor_output, 1)
    initialized_result = initialized.get("result")
    assert isinstance(initialized_result, dict)
    initialized_capabilities = initialized_result.get("capabilities")
    assert isinstance(initialized_capabilities, dict)
    assert "completionProvider" in initialized_capabilities
    assert "definitionProvider" in initialized_capabilities
    send(editor_output, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": path.as_uri(),
                    "languageId": "python",
                    "version": 1,
                    "text": source,
                }
            },
        },
    )

    diagnostic_response: JsonObject | None = None
    for request_id in range(2, 5):
        send(
            editor_output,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "textDocument/diagnostic",
                "params": {"textDocument": {"uri": path.as_uri()}},
            },
        )
        candidate = response_for(editor_input, editor_output, request_id)
        error = candidate.get("error")
        if not isinstance(error, dict) or "subsequent mutation" not in str(
            error.get("message")
        ):
            diagnostic_response = candidate
            break
    assert diagnostic_response is not None
    diagnostic_result = diagnostic_response.get("result")
    assert isinstance(diagnostic_result, dict)
    assert diagnostic_result.get("items") == []

    result_line = source[: source.index("result_1 =")].count("\n")
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": path.as_uri()},
                "position": {"line": result_line, "character": 0},
            },
        },
    )
    hover = response_for(editor_input, editor_output, 10)
    hover_result = hover.get("result")
    assert isinstance(hover_result, dict)
    contents = hover_result.get("contents")
    assert isinstance(contents, dict)
    assert "tuple[int, Position, Velocity] | None" in str(contents.get("value"))

    call_offset = source.index("world.query") + len("world.")
    call_prefix = source[:call_offset]
    call_line = call_prefix.count("\n")
    call_character = (
        len(call_prefix[call_prefix.rfind("\n") + 1 :].encode("utf-16-le")) // 2
    )
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": path.as_uri()},
                "position": {
                    "line": call_line,
                    "character": call_character,
                },
            },
        },
    )
    completion = response_for(editor_input, editor_output, 11)
    completion_result = completion.get("result")
    assert isinstance(completion_result, dict)
    completion_items = completion_result.get("items")
    assert isinstance(completion_items, list)
    assert any(
        isinstance(item, dict) and item.get("label") == "query"
        for item in completion_items
    )

    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "textDocument/definition",
            "params": {
                "textDocument": {"uri": path.as_uri()},
                "position": {
                    "line": call_line,
                    "character": call_character,
                },
            },
        },
    )
    definition = response_for(editor_input, editor_output, 12)
    definition_result = definition.get("result")
    locations = (
        definition_result
        if isinstance(definition_result, list)
        else [definition_result]
    )
    assert locations
    location = locations[0]
    assert isinstance(location, dict)
    location_range = location.get("range")
    assert isinstance(location_range, dict)
    start = location_range.get("start")
    assert isinstance(start, dict)
    assert start.get("line") == source[: source.index("def query")].count("\n")

    each_offset = source.index("Each")
    each_prefix = source[:each_offset]
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": path.as_uri()},
                "position": {
                    "line": each_prefix.count("\n"),
                    "character": each_offset - each_prefix.rfind("\n") - 1,
                },
            },
        },
    )
    marker_hover = response_for(editor_input, editor_output, 13)
    assert "heterogeneous variadic parameter" in str(marker_hover.get("result"))

    entity_offset = source.rindex("EntityId")
    entity_prefix = source[:entity_offset]
    send(
        editor_output,
        {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": path.as_uri()},
                "position": {
                    "line": entity_prefix.count("\n"),
                    "character": entity_offset - entity_prefix.rfind("\n") - 1,
                },
            },
        },
    )
    custom_hover = response_for(editor_input, editor_output, 14)
    assert "An entity identifier." in str(custom_hover.get("result"))

    send(editor_output, {"jsonrpc": "2.0", "id": 15, "method": "shutdown"})
    assert response_for(editor_input, editor_output, 15)["id"] == 15
    send(editor_output, {"jsonrpc": "2.0", "method": "exit"})
    proxy_thread.join(timeout=5.0)
    assert completed == [Ok(None)]
