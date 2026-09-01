import sys
from pathlib import Path

import pytest
from returns.result import Result, Success

from typeforge.adapters.mypy import (
    MypyAdapter,
    MypyConfiguration,
    MypyRunOutput,
    MypyRunRequest,
)
from typeforge.analysis.model import (
    AnalysisRequest,
    CheckerError,
    DiagnosticSeverity,
    MappingKind,
    SourceMapping,
    SourcePosition,
    SourceSpan,
    VirtualDocument,
)
from typeforge.overlay.transform import transform_source


def test_mypy_normalizes_shadow_file_diagnostics(tmp_path: Path) -> None:
    source_path = tmp_path / "module.py"
    authored_text = "value: int = 1\n"
    generated_text = 'value: int = "wrong"\n'
    source_path.write_text(authored_text)

    def run_mypy(request: MypyRunRequest) -> Success[MypyRunOutput]:
        assert request.source_path == source_path
        assert request.generated_text == generated_text
        return Success(
            MypyRunOutput(
                return_code=1,
                stdout=(
                    '{"file":"module.py","line":1,"column":13,'
                    '"end_line":1,"end_column":20,'
                    '"message":"Incompatible assignment",'
                    '"code":"assignment","severity":"error"}\n'
                ),
                stderr="",
            )
        )

    result = MypyAdapter(runner=run_mypy).analyze(
        AnalysisRequest(
            document=document(source_path, authored_text, generated_text),
            project_root=tmp_path,
        )
    )

    assert isinstance(result, Success)
    assert source_path.read_text() == authored_text
    assert len(result.unwrap().diagnostics) == 1
    diagnostic = result.unwrap().diagnostics[0]
    assert diagnostic.path == source_path
    assert diagnostic.severity is DiagnosticSeverity.ERROR
    assert diagnostic.code == "assignment"
    assert diagnostic.span.start.line == 0
    assert diagnostic.span.start.column == 13
    assert diagnostic.span.start.offset == 13


def test_mypy_checks_same_file_ecs_inference_without_source_edits(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "ecs.py"
    authored_text = "class World: ...\n"
    generated_text = """from typing import TYPE_CHECKING, assert_type, overload

class Component: ...
class Position(Component): ...
class Velocity(Component): ...
class Option[T: Component]: ...

class World[E]:
    if TYPE_CHECKING:
        @overload
        def query[T1, T2: Component](
            self,
            first: type[T1],
            second: type[Option[T2]],
            /,
        ) -> tuple[E, T1, T2 | None] | None: ...

        @overload
        def query[T1, T2](
            self,
            first: type[T1],
            second: type[T2],
            /,
        ) -> tuple[E, T1, T2] | None: ...

    def query(self, *components: type[object]) -> object:
        raise NotImplementedError

world = World[int]()
assert_type(
    world.query(Position, Velocity),
    tuple[int, Position, Velocity] | None,
)
assert_type(
    world.query(Position, Option[Velocity]),
    tuple[int, Position, Velocity | None] | None,
)
"""
    source_path.write_text(authored_text)

    result = MypyAdapter(
        configuration=MypyConfiguration(command=(sys.executable, "-m", "mypy"))
    ).analyze(
        AnalysisRequest(
            document=document(source_path, authored_text, generated_text),
            project_root=tmp_path,
            extra_arguments=("--strict", "--python-version", "3.14"),
        )
    )

    assert isinstance(result, Success), result
    assert result.unwrap().diagnostics == ()
    assert source_path.read_text() == authored_text
    assert not (tmp_path / ".mypy_cache").exists()


def test_default_mypy_adapter_declares_in_memory_documents() -> None:
    assert MypyAdapter().capabilities.in_memory_documents


def test_in_memory_mypy_resolves_config_paths_from_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = project / "pyproject.toml"
    config.write_text(
        '[tool.mypy]\nmypy_path = "stubs"\npython_version = "3.14"\n',
        encoding="utf-8",
    )
    stubs = project / "stubs"
    stubs.mkdir()
    (stubs / "support.pyi").write_text("class Item: ...\n", encoding="utf-8")
    source_path = project / "main.py"
    source = "from support import Item\nvalue: Item = Item()\n"
    source_path.write_text(source, encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    result = MypyAdapter().analyze(
        AnalysisRequest(
            document=document(source_path, source, source),
            project_root=project,
            config_file=config,
        )
    )

    assert isinstance(result, Success), result
    assert result.unwrap().diagnostics == ()
    assert Path.cwd() == outside


def test_mypy_maps_generated_diagnostics_to_the_authored_origin(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "module.py"
    authored_text = "type Output = int\n"
    generated_prefix = "generated_error\n"
    generated_text = generated_prefix + authored_text
    source_path.write_text(authored_text)
    origin = SourceSpan(position(0, 0, 0), position(4, 0, 4))
    generated = SourceSpan(
        position(0, 0, 0),
        position(len(generated_prefix), 1, 0),
    )
    virtual_document = VirtualDocument(
        uri=source_path.as_uri(),
        path=source_path,
        version=1,
        authored_text=authored_text,
        generated_text=generated_text,
        mappings=(SourceMapping(origin, generated, MappingKind.GENERATED),),
    )

    def run_mypy(
        request: MypyRunRequest,
    ) -> Result[MypyRunOutput, CheckerError]:
        del request
        return Success(
            MypyRunOutput(
                return_code=1,
                stdout=(
                    f'{{"file":"{source_path}","line":1,"column":0,'
                    '"end_line":1,"end_column":9,"message":"Generated error",'
                    '"code":"misc","severity":"error"}\n'
                ),
                stderr="",
            )
        )

    result = MypyAdapter(runner=run_mypy).analyze(
        AnalysisRequest(document=virtual_document, project_root=tmp_path)
    )

    assert isinstance(result, Success)
    assert result.unwrap().diagnostics[0].span == SourceSpan(origin.start, origin.start)


def test_mypy_checks_typeforge_overlay_for_same_file_calls(tmp_path: Path) -> None:
    source_path = tmp_path / "ecs.py"
    authored_text = """from typing import Protocol, assert_type

from typeforge import Case, Collect, Default, Each, Map, Value

class Component(Protocol):
    def __hash__(self) -> int: ...

class Option[T: Component]: ...
class Position: ...
class Velocity:
    def __hash__(self) -> int:
        return 1

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

world = World[int]()
assert_type(
    world.query(Position, Velocity),
    tuple[int, Position, Velocity] | None,
)
assert_type(
    world.query(Position, Option[Velocity]),
    tuple[int, Position, Velocity | None] | None,
)
"""
    source_path.write_text(authored_text)
    transformed = transform_source(authored_text, source_path, maximum_arity=3)
    assert isinstance(transformed, Success), transformed

    result = MypyAdapter().analyze(
        AnalysisRequest(
            document=transformed.unwrap(),
            project_root=tmp_path,
            extra_arguments=("--strict", "--python-version", "3.14"),
        )
    )

    assert isinstance(result, Success), result
    assert result.unwrap().diagnostics == ()
    assert source_path.read_text() == authored_text


def test_mypy_maps_utf8_byte_columns_to_authored_characters(tmp_path: Path) -> None:
    source_path = tmp_path / "unicode.py"
    authored_text = 'emoji = "😀"; value: int = "wrong"\n'
    source_path.write_text(authored_text, encoding="utf-8")

    result = MypyAdapter().analyze(
        AnalysisRequest(
            document=document(source_path, authored_text, authored_text),
            project_root=tmp_path,
        )
    )

    assert isinstance(result, Success)
    assert len(result.unwrap().diagnostics) == 1
    span = result.unwrap().diagnostics[0].span
    assert authored_text[span.start.offset : span.end.offset] == '"wrong"'


def document(path: Path, authored_text: str, generated_text: str) -> VirtualDocument:
    return VirtualDocument(
        uri=path.as_uri(),
        path=path,
        version=1,
        authored_text=authored_text,
        generated_text=generated_text,
        mappings=(),
    )


def position(offset: int, line: int, column: int) -> SourcePosition:
    return SourcePosition(offset=offset, line=line, column=column)
