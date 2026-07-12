import sys
from pathlib import Path

from typeforge._result import Ok
from typeforge.adapters.pyrefly import PyreflyAdapter
from typeforge.analysis.model import (
    AnalysisRequest,
    DiagnosticSeverity,
    HoverQuery,
    MappingKind,
    SourceMapping,
    SourcePosition,
    SourceSpan,
    VirtualDocument,
)
from typeforge.overlay import transform_source

FAKE_SERVER = r"""
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


initialize = read_message()
write_message({
    "jsonrpc": "2.0",
    "id": initialize["id"],
    "result": {"capabilities": {}},
})
assert read_message()["method"] == "initialized"
opened = read_message()
document = opened["params"]["textDocument"]
assert document["uri"].endswith("/ecs.py")
assert "generated_query_result" in document["text"]
write_message({
    "jsonrpc": "2.0",
    "method": "textDocument/publishDiagnostics",
    "params": {
        "uri": document["uri"],
        "version": document["version"],
        "diagnostics": [{
            "range": {
                "start": {"line": 2, "character": 0},
                "end": {"line": 2, "character": 6},
            },
            "severity": 2,
            "code": "bad-query",
            "source": "pyrefly",
            "message": "query result is incompatible",
        }],
    },
})
diagnostic_request = read_message()
assert diagnostic_request["method"] == "textDocument/diagnostic"
write_message({
    "jsonrpc": "2.0",
    "id": diagnostic_request["id"],
    "result": {"kind": "full", "items": []},
})
hover = read_message()
assert hover["method"] == "textDocument/hover"
assert hover["params"]["position"] == {"line": 2, "character": 0}
write_message({
    "jsonrpc": "2.0",
    "id": hover["id"],
    "result": {
        "contents": {
            "kind": "markdown",
            "value": "```python\ntuple[int, Position]\n```",
        },
        "range": {
            "start": {"line": 2, "character": 0},
            "end": {"line": 2, "character": 6},
        },
    },
})
shutdown = read_message()
assert shutdown["method"] == "shutdown"
write_message({"jsonrpc": "2.0", "id": shutdown["id"], "result": None})
assert read_message()["method"] == "exit"
""".lstrip()


def position(source: str, offset: int) -> SourcePosition:
    prefix = source[:offset]
    line = prefix.count("\n")
    newline = prefix.rfind("\n")
    column = offset if newline < 0 else offset - newline - 1
    return SourcePosition(offset, line, column)


def span(source: str, start: int, end: int) -> SourceSpan:
    return SourceSpan(position(source, start), position(source, end))


def test_pyrefly_analyzes_generated_text_under_the_authored_uri(
    tmp_path: Path,
) -> None:
    server = tmp_path / "fake_pyrefly.py"
    server.write_text(FAKE_SERVER, encoding="utf-8")
    authored = "header\nresult = query()\n"
    inserted = "generated_query_result = None\n"
    generated = f"{inserted}{authored}"
    document_path = tmp_path / "ecs.py"
    insertion_length = len(inserted)
    document = VirtualDocument(
        uri=document_path.as_uri(),
        path=document_path,
        version=7,
        authored_text=authored,
        generated_text=generated,
        mappings=(
            SourceMapping(
                authored=span(authored, 0, 0),
                generated=span(generated, 0, insertion_length),
                origin=MappingKind.GENERATED,
            ),
            SourceMapping(
                authored=span(authored, 0, len(authored)),
                generated=span(generated, insertion_length, len(generated)),
                origin=MappingKind.AUTHORED,
            ),
        ),
    )
    query_position = position(authored, authored.index("result"))
    result = PyreflyAdapter(
        command=(sys.executable, str(server)), timeout_seconds=5.0
    ).analyze(
        AnalysisRequest(
            document=document,
            project_root=tmp_path,
            hover_queries=(HoverQuery(query_position),),
        )
    )

    assert isinstance(result, Ok)
    assert len(result.value.diagnostics) == 1
    diagnostic = result.value.diagnostics[0]
    assert diagnostic.path == document_path
    assert diagnostic.span == span(authored, 7, 13)
    assert diagnostic.severity is DiagnosticSeverity.WARNING
    assert diagnostic.code == "bad-query"
    assert diagnostic.message == "query result is incompatible"
    assert len(result.value.hovers) == 1
    hover = result.value.hovers[0]
    assert hover.path == document_path
    assert hover.span == span(authored, 7, 13)
    assert "tuple[int, Position]" in hover.contents


def test_pyrefly_reports_missing_binary_as_typed_failure(tmp_path: Path) -> None:
    source = "value = 1\n"
    document_path = tmp_path / "sample.py"
    document = VirtualDocument(
        uri=document_path.as_uri(),
        path=document_path,
        version=1,
        authored_text=source,
        generated_text=source,
        mappings=(
            SourceMapping(
                authored=span(source, 0, len(source)),
                generated=span(source, 0, len(source)),
                origin=MappingKind.AUTHORED,
            ),
        ),
    )

    result = PyreflyAdapter(command=("typeforge-missing-pyrefly",)).analyze(
        AnalysisRequest(document=document, project_root=tmp_path)
    )

    assert not isinstance(result, Ok)
    assert result.error.checker == "pyrefly"
    assert result.error.detail is not None
    assert result.error.detail.startswith("spawn:")


def test_installed_pyrefly_accepts_in_memory_document(tmp_path: Path) -> None:
    source = 'value: int = "wrong"\n'
    document_path = tmp_path / "actual.py"
    document_path.write_text("value: int = 1\n", encoding="utf-8")
    document = VirtualDocument(
        uri=document_path.as_uri(),
        path=document_path,
        version=1,
        authored_text=source,
        generated_text=source,
        mappings=(
            SourceMapping(
                authored=span(source, 0, len(source)),
                generated=span(source, 0, len(source)),
                origin=MappingKind.AUTHORED,
            ),
        ),
    )
    pyrefly = Path(sys.executable).with_name("pyrefly")

    result = PyreflyAdapter(
        command=(str(pyrefly), "lsp"), timeout_seconds=30.0
    ).analyze(
        AnalysisRequest(
            document=document,
            project_root=tmp_path,
            hover_queries=(HoverQuery(position(source, 0)),),
        )
    )

    assert isinstance(result, Ok)
    assert any("Literal['wrong']" in item.message for item in result.value.diagnostics)


def test_pyrefly_checks_bounded_ecs_overlay_and_hovers_exact_type(
    tmp_path: Path,
) -> None:
    source = """
from dataclasses import dataclass
from typing import Protocol, assert_type

from typeforge import Case, Collect, Default, Each, Map, Value


class Component(Protocol):
    def __hash__(self) -> int: ...


class Entity(Protocol):
    def __hash__(self) -> int: ...


@dataclass(frozen=True)
class Option[T: Component]:
    value: T


type QueryResult[T] = Map[
    T,
    Case[Option[Value], Value | None],
    Default[T],
]


class World[E: Entity]:
    def query[T](
        self,
        *components: Each[type[T]],
    ) -> tuple[E, *Collect[QueryResult[T]]] | None:
        raise NotImplementedError


@dataclass(frozen=True)
class Position:
    x: float


@dataclass(frozen=True)
class Velocity:
    dx: float


world = World[int]()
result_1 = world.query(Position, Velocity)
assert_type(result_1, tuple[int, Position, Velocity] | None)
result_2 = world.query(Position, Option[Velocity])
assert_type(result_2, tuple[int, Position, Velocity | None] | None)
""".lstrip()
    path = tmp_path / "ecs.py"
    path.write_text(source, encoding="utf-8")
    transformed = transform_source(source, path, maximum_arity=2, version=3)
    assert isinstance(transformed, Ok)
    assert "# typeforge: overlay" in transformed.value.generated_text
    hover_offset = source.index("result_1 =")
    pyrefly = Path(sys.executable).with_name("pyrefly")

    result = PyreflyAdapter(command=(str(pyrefly), "lsp")).analyze(
        AnalysisRequest(
            document=transformed.value,
            project_root=tmp_path,
            hover_queries=(HoverQuery(position(source, hover_offset)),),
        )
    )

    assert isinstance(result, Ok)
    assert result.value.diagnostics == ()
    assert len(result.value.hovers) == 1
    assert "tuple[int, Position, Velocity] | None" in (result.value.hovers[0].contents)
