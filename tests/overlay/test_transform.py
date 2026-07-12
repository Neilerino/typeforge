import ast
from pathlib import Path
from subprocess import run
from sys import executable

from typeforge._result import Err, Ok
from typeforge.analysis import MappingKind
from typeforge.analysis.mapping import (
    authored_to_generated,
    generated_to_authored,
    position_from_offset,
)
from typeforge.overlay import OverlayError, transform_source


def test_enriched_function_is_overlaid_without_touching_authored_text() -> None:
    source = (
        '"""Example."""\n'
        "from typeforge import Collect, Each\n\n"
        "def collect[*Ts](*values: Each[Ts]) -> Collect[Ts]:\n"
        "    return values\n\n"
        'result = collect(1, "two")\n'
    )

    transformed = transform_source(source, Path("example.py"), maximum_arity=2)

    assert isinstance(transformed, Ok)
    document = transformed.value
    assert document.authored_text == source
    assert "if TYPE_CHECKING:  # typeforge: overlay" in document.generated_text
    assert "@overload\n    def collect() -> tuple[()]: ..." in document.generated_text
    assert (
        "def collect[Ts1, Ts2](values_1: Ts1, values_2: Ts2, /) -> tuple[Ts1, Ts2]: ..."
    ) in document.generated_text
    assert document.generated_text.endswith('result = collect(1, "two")\n')
    ast.parse(document.generated_text, filename="example.py", type_comments=True)


def test_positions_at_an_insertion_boundary_select_authored_source() -> None:
    source = (
        "from typeforge import Collect, Each\n\n"
        "def collect[T](*values: Each[T]) -> Collect[T]:\n"
        "    return values\n"
    )
    transformed = transform_source(source, Path("example.py"), maximum_arity=1)
    assert isinstance(transformed, Ok)
    document = transformed.value
    authored_offset = source.index("def collect")
    generated_offset = document.generated_text.rindex("def collect")

    generated = authored_to_generated(
        document, position_from_offset(source, authored_offset)
    )
    authored = generated_to_authored(
        document, position_from_offset(document.generated_text, generated_offset)
    )

    assert generated.offset == generated_offset
    assert authored.offset == authored_offset


def test_enriched_method_is_inserted_inside_its_owning_class() -> None:
    source = (
        "from typeforge import Collect, Each\n\n"
        "class Factory:\n"
        "    async def create[T](self, *values: Each[T]) -> Collect[T]:\n"
        "        return values\n"
    )

    transformed = transform_source(source, Path("factory.py"), maximum_arity=1)

    assert isinstance(transformed, Ok)
    generated = transformed.value.generated_text
    assert "class Factory:\n    if TYPE_CHECKING:" in generated
    assert "        @overload\n        async def create(self: Any, /)" in generated
    assert "async def create[T1](self: Any, values_1: T1, /)" in generated
    assert "    async def create[T](self, *values: Each[T])" in generated
    ast.parse(generated, filename="factory.py", type_comments=True)


def test_map_aliases_are_expanded_before_overlay_lowering() -> None:
    source = (
        "from typeforge import Case, Default, Map\n\n"
        "type Encoded[T] = Map[T, Case[int, bytes], Default[str]]\n\n"
        "def encode[T](value: T) -> Encoded[T]:\n"
        "    return str(value)\n"
    )

    transformed = transform_source(source, Path("encoding.py"), maximum_arity=1)

    assert isinstance(transformed, Ok)
    assert "type Encoded[T] = object" in transformed.value.generated_text
    assert "def encode(value: int) -> bytes: ..." in (transformed.value.generated_text)
    assert "def encode[T](value: T) -> bytes | str: ..." in (
        transformed.value.generated_text
    )


def test_transform_is_idempotent() -> None:
    source = (
        "from typeforge import Collect, Each\n"
        "def collect[T](*values: Each[T]) -> Collect[T]: ...\n"
    )
    first = transform_source(source, Path("example.py"), maximum_arity=2)
    assert isinstance(first, Ok)

    second = transform_source(
        first.value.generated_text,
        Path("example.py"),
        maximum_arity=2,
    )

    assert isinstance(second, Ok)
    assert second.value.generated_text == first.value.generated_text
    assert second.value.generated_text.count("# typeforge: overlay\n") == 1


def test_mappings_cover_authored_regions_and_generated_overloads() -> None:
    source = (
        "from typeforge import Collect, Each\n"
        "def collect[T](*values: Each[T]) -> Collect[T]: ...\n"
        "answer = 42\n"
    )

    transformed = transform_source(source, Path("example.py"), maximum_arity=1)

    assert isinstance(transformed, Ok)
    document = transformed.value
    authored = tuple(
        mapping
        for mapping in document.mappings
        if mapping.origin is MappingKind.AUTHORED
    )
    generated = tuple(
        mapping
        for mapping in document.mappings
        if mapping.origin is MappingKind.GENERATED
    )
    assert authored
    assert len(generated) == 2
    answer_offset = source.index("answer")
    generated_answer_offset = document.generated_text.index("answer")
    assert any(
        mapping.authored.start.offset <= answer_offset < mapping.authored.end.offset
        and mapping.generated.start.offset
        <= generated_answer_offset
        < mapping.generated.end.offset
        for mapping in authored
    )
    overload_mapping = generated[-1]
    assert overload_mapping.authored.start.line == 1
    assert document.generated_text[
        overload_mapping.generated.start.offset : overload_mapping.generated.end.offset
    ].startswith("if TYPE_CHECKING")
    generated_parameter = document.generated_text.index("values_1")
    authored_position = generated_to_authored(
        document,
        position_from_offset(document.generated_text, generated_parameter),
    )
    assert authored_position == overload_mapping.authored.start


def test_ordinary_source_is_returned_unchanged() -> None:
    source = "def identity[T](value: T) -> T:\n    return value\n"

    transformed = transform_source(source, Path("ordinary.py"))

    assert isinstance(transformed, Ok)
    assert transformed.value.authored_text == source
    assert transformed.value.generated_text == source
    assert len(transformed.value.mappings) == 1
    assert transformed.value.mappings[0].origin is MappingKind.AUTHORED


def test_syntax_and_configuration_failures_are_typed() -> None:
    syntax = transform_source("def broken(: ...\n", Path("broken.py"))
    frontier = transform_source("pass\n", Path("valid.py"), maximum_arity=-1)

    assert isinstance(syntax, Err)
    assert isinstance(syntax.error, OverlayError)
    assert syntax.error.code == "syntax"
    assert isinstance(frontier, Err)
    assert isinstance(frontier.error, OverlayError)
    assert frontier.error.code == "invalid_arity"


def test_mypy_consumes_same_file_method_overlay(tmp_path: Path) -> None:
    source = (
        "from typing import assert_type\n"
        "from typeforge import Collect, Each\n\n"
        "class Factory:\n"
        "    def create[T](self, *values: Each[T]) -> Collect[T]:\n"
        "        raise NotImplementedError\n\n"
        "factory = Factory()\n"
        'assert_type(factory.create(1, "two"), tuple[int, str])\n'
    )
    transformed = transform_source(source, tmp_path / "same_file.py", maximum_arity=2)
    assert isinstance(transformed, Ok)
    path = tmp_path / "same_file.py"
    path.write_text(transformed.value.generated_text, encoding="utf-8")

    completed = run(
        (
            executable,
            "-m",
            "mypy",
            "--strict",
            "--python-version",
            "3.14",
            str(path),
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_mypy_consumes_bounded_structural_map_overlay(tmp_path: Path) -> None:
    source = (
        "from dataclasses import dataclass\n"
        "from typing import Protocol, assert_type\n"
        "from typeforge import Case, Collect, Default, Each, Map, Value\n\n"
        "class Component(Protocol):\n"
        "    def __hash__(self) -> int: ...\n\n"
        "@dataclass(frozen=True)\n"
        "class Option[T: Component]:\n"
        "    value: T\n\n"
        "type QueryResult[T] = Map[\n"
        "    T, Case[Option[Value], Value | None], Default[T]\n"
        "]\n\n"
        "class World:\n"
        "    def query[T](\n"
        "        self, *components: Each[type[T]]\n"
        "    ) -> Collect[QueryResult[T]]:\n"
        "        raise NotImplementedError\n\n"
        "@dataclass(frozen=True)\n"
        "class Position:\n"
        "    x: float\n\n"
        "@dataclass(frozen=True)\n"
        "class Velocity:\n"
        "    dx: float\n\n"
        "world = World()\n"
        "assert_type(world.query(Position, Velocity), tuple[Position, Velocity])\n"
        "assert_type(\n"
        "    world.query(Position, Option[Velocity]),\n"
        "    tuple[Position, Velocity | None],\n"
        ")\n"
    )
    transformed = transform_source(source, tmp_path / "ecs.py", maximum_arity=2)
    assert isinstance(transformed, Ok)
    assert "query[T1: Component]" in transformed.value.generated_text
    path = tmp_path / "ecs.py"
    path.write_text(transformed.value.generated_text, encoding="utf-8")

    completed = run(
        (
            executable,
            "-m",
            "mypy",
            "--strict",
            "--python-version",
            "3.14",
            str(path),
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
