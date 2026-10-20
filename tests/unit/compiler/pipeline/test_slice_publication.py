"""Published slice relationships are consumed without Typeforge processing."""

import ast
import json
from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from returns.result import Failure

from typeforge.compiler.emission import EmissionError
from typeforge.compiler.pipeline import compile_source, generate_module
from typeforge.compiler.specialization import LoweringError, LoweringErrorCode
from typeforge.overlay import transform_source

LIBRARY = """from dataclasses import dataclass
from typing import Literal, TypedDict
from typeforge import Capture, Collect, Each, Map

Item = Capture("Item")
from typeforge._markers import All, Any, Assignable, Equal, Not

VERSION: int = 1 // 0

class Row(TypedDict):
    name: str

@dataclass(frozen=True)
class Option[T]:
    value: T

type Numeric = Assignable[int]
type Encoded[T] = Map[T, int: str | None, ...: bytes]
type QueryResult[T] = Map[T, Option[Item]: Item | None, ...: T]

def identity[T](value: T) -> T: ...
def encode[T](value: T) -> Encoded[T]: ...
def read[T](value: T) -> Map[T, Literal["text"]: str, ...: bytes]: ...
def flag[T](value: T) -> Map[T, True: str, ...: bytes]: ...
def number[T](value: T) -> Map[T, -1: str, ...: bytes]: ...
def normalize[T](value: T) -> Map[T, Numeric: str, ...: bytes]: ...
def together[T](value: T) -> Map[
    T, All[Assignable[int], Equal[int]]: str, ...: bytes
]: ...
def exclude_bool[T](value: T) -> Map[
    T, All[Assignable[int], Not[Equal[bool]]]: str, ...: bytes
]: ...
def either[T](value: T) -> Map[
    T, Any[Equal[bytes], Equal[str]]: str, ...: float
]: ...
def preserve[T](value: T) -> Map[T, int: str, ...: T]: ...
def partial[T](value: T) -> Map[T, int: str]: ...

class Store:
    def query[T](self, *items: Each[type[T]]) -> Collect[QueryResult[T]]: ...
"""

CONSUMER = """\
from typing import assert_type
from library import (
    VERSION, Encoded, Option, Row, Store, either, encode, exclude_bool, flag, identity,
    normalize, number, partial, preserve, read, together,
)

assert_type(VERSION, int)
row: Row = {"name": "Ada"}
assert_type(identity(row), Row)
assert_type(Option(1).value, int)
assert_type(read("text"), str)
assert_type(read("binary"), str | bytes)
assert_type(flag(True), str)
assert_type(number(-1), str)
assert_type(normalize(1), str)
assert_type(normalize(True), str)
assert_type(together(1), str)
assert_type(exclude_bool(1), str | bytes)
assert_type(exclude_bool(True), bytes)
assert_type(either(b"text"), str)
assert_type(either("text"), str)
assert_type(encode(1), str | None)
assert_type(encode(b"text"), str | None | bytes)
assert_type(partial(1), str)

def inspect(value: int | str, data: bytes, alias: Encoded[int]) -> None:
    assert_type(encode(value), str | None | bytes)
    assert_type(preserve(data), str | bytes)
    assert_type(alias, object)

store = Store()
assert_type(store.query(), tuple[()])
assert_type(store.query(int), tuple[int])
assert_type(store.query(int, Option[str]), tuple[int, str | None])
assert_type(store.query(Option[int | str]), tuple[int | str | None])
assert_type(store.query(int, str, bytes), tuple[object, ...])
"""


def _checker_command(checker: str, directory: Path) -> tuple[str, ...]:
    command = str(Path(executable).with_name(checker))
    if checker == "mypy":
        return command, "--strict", "--no-incremental", "consumer.py"

    if checker == "pyright":
        (directory / "pyrightconfig.json").write_text(
            json.dumps({"pythonVersion": "3.14", "typeCheckingMode": "standard"})
        )
        return command, "consumer.py"

    (directory / "pyrefly.toml").write_text('python-version = "3.14"\n')
    return command, "check", "--config", "pyrefly.toml", "consumer.py"


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
@pytest.mark.parametrize("maximum_arity", [2, 3])
def test_slice_stubs_preserve_complete_finite_interfaces(
    tmp_path: Path, checker: str, maximum_arity: int
) -> None:
    library = tmp_path / "library.py"
    library.write_text(LIBRARY)
    published = generate_module(library, maximum_arity=maximum_arity).unwrap().content
    tree = ast.parse(published)
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert all(node.module != "typeforge" for node in imports)
    assert not any(isinstance(node, ast.Slice) for node in ast.walk(tree))
    library.with_suffix(".pyi").write_text(published)

    # A consumer needs only the published interface, with no authored module.
    library.unlink()
    consumer = tmp_path / "consumer.py"
    consumer_source = CONSUMER
    if maximum_arity == 3:
        consumer_source = consumer_source.replace(
            "store.query(int, str, bytes), tuple[object, ...]",
            "store.query(int, str, bytes), tuple[int, str, bytes]",
        )

    consumer.write_text(consumer_source)
    command = _checker_command(checker, tmp_path)
    result = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, published + result.stdout + result.stderr

    consumer.write_text(
        consumer_source.replace("encode(1), str | None", "encode(1), bytes")
    )
    result = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "str" in result.stdout + result.stderr

    # Consumer calls cannot change the published finite frontier.
    library.write_text(LIBRARY)
    assert (
        generate_module(library, maximum_arity=maximum_arity).unwrap().content
        == published
    )


@pytest.mark.parametrize(
    ("signature", "code"),
    [
        (
            "def choose(value: int | str) -> Map[int | str, int: bytes]: ...",
            LoweringErrorCode.MISSING_CONTROLLER,
        ),
        (
            "def choose[T]() -> Map[T, int: bytes]: ...",
            LoweringErrorCode.MISSING_CONTROLLER,
        ),
        (
            "def choose[T](value: T) -> Map[T, int: str, int: bytes]: ...",
            LoweringErrorCode.DUPLICATE_MAP_CASE,
        ),
        (
            "def choose[T](value: T) -> "
            "Map[T, Assignable[list[T], list[int]]: str]: ...",
            LoweringErrorCode.UNSUPPORTED_PREDICATE,
        ),
        (
            "def choose[T](value: Each[T]) -> Collect[Map[T, int: str]]: ...",
            LoweringErrorCode.INVALID_EACH_POSITION,
        ),
    ],
)
def test_unsupported_slice_callables_return_typed_failures(
    tmp_path: Path, signature: str, code: LoweringErrorCode
) -> None:
    path = tmp_path / "unsupported.py"
    source = (
        "from typeforge._markers import Assignable\n"
        "from typeforge import Collect, Each, Map\n" + signature
    )
    path.write_text(source)

    result = generate_module(path, maximum_arity=2)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, LoweringError)
    assert error.code is code
    assert error.declaration == "choose"
    assert compile_source(source, path, maximum_arity=2) == result


def test_unbounded_capture_does_not_publish_a_partial_interface(tmp_path: Path) -> None:
    path = tmp_path / "unsupported.py"
    path.write_text(
        "from typeforge import Capture, Map\n"
        'Item = Capture("Item")\n'
        "def identity[T](value: T) -> T: ...\n"
        "def choose[T](value: T) -> "
        "Map[T, list[Item]: tuple[Item, ...], ...: bytes]: ...\n"
    )

    result = generate_module(path, maximum_arity=2)
    assert isinstance(result, Failure)
    assert result == Failure(EmissionError("unlowered type expression: CaptureType"))


def test_publication_and_overlay_keep_distinct_alias_bounds(tmp_path: Path) -> None:
    path = tmp_path / "bounds.py"
    source = (
        "from typeforge import Map\n"
        "type Encoded[T] = Map[T, int: str | None, ...: bytes]\n"
        "def encode[T](value: T) -> Encoded[T]: ...\n"
    )
    path.write_text(source)

    published = generate_module(path, maximum_arity=2).unwrap().content
    overlay = transform_source(source, path, maximum_arity=2).unwrap()

    assert "type Encoded[T] = object" in published
    assert "type Encoded[T] = str | None | bytes" in overlay.generated_text
    assert "def encode(value: int) -> str | None" in published
    assert "def encode(value: int) -> str | None" in overlay.generated_text
