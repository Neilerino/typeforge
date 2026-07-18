from dataclasses import dataclass
from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from returns.result import Success

from typeforge.compiler.pipeline import generate_module


@dataclass(frozen=True, slots=True)
class Checker:
    name: str
    arguments: tuple[str, ...]


CHECKERS = (
    Checker(
        "mypy",
        (executable, "-m", "mypy", "--strict", "--python-version", "3.14"),
    ),
    Checker(
        "pyright",
        (executable, "-m", "pyright", "--pythonversion", "3.14"),
    ),
)


LIBRARY_SOURCE = """
from external import Parser
from typing import Literal, TypedDict

from typeforge import (
    All,
    Any,
    Assignable,
    Case,
    Collect,
    Default,
    Each,
    Equal,
    Field,
    If,
    Key,
    Map,
    MapFields,
    Not,
    Value,
)


def combine[T](*parsers: Each[Parser[T]]) -> Parser[Collect[T]]:
    raise NotImplementedError


def read[M](mode: M) -> If[Equal[M, Literal["text"]], str, bytes]:
    raise NotImplementedError


def normalize[T](value: T) -> If[Assignable[T, str], str, bytes]:
    raise NotImplementedError


def choose_all[T](value: T) -> If[
    All[Equal[T, str], Assignable[T, str]],
    str,
    bytes,
]:
    raise NotImplementedError


def choose_any[T](value: T) -> If[
    Any[Equal[T, Literal["text"]], Equal[T, bytes]],
    str,
    float,
]:
    raise NotImplementedError


def reject_bytes[T](value: T) -> If[Not[Equal[T, bytes]], str, bytes]:
    raise NotImplementedError


def serialize[T](value: T) -> Map[T, Case[int, float], Default[T]]:
    raise NotImplementedError


class User(TypedDict):
    name: str
    age: int


type Public[T] = MapFields[T, Field[Key, Value]]


def publicize[T](value: T) -> Public[T]:
    raise NotImplementedError
""".lstrip()


CONSUMER_SOURCE = """
from typing import assert_type

from external import Parser
from library import (
    Public_User,
    User,
    choose_all,
    choose_any,
    combine,
    normalize,
    publicize,
    read,
    reject_bytes,
    serialize,
)

integer_parser = Parser[int]()
string_parser = Parser[str]()
assert_type(combine(integer_parser, string_parser), Parser[tuple[int, str]])
assert_type(read("text"), str)
assert_type(normalize("value"), str)
assert_type(choose_all("value"), str)
assert_type(choose_any("text"), str)
assert_type(reject_bytes(b"value"), bytes)
assert_type(serialize(1), float)
user: User = {"name": "Ada", "age": 37}
assert_type(publicize(user), Public_User)
""".lstrip()


@pytest.mark.parametrize("checker", CHECKERS, ids=lambda checker: checker.name)
def test_generated_stub_is_consumed_by_existing_checkers(
    tmp_path: Path,
    checker: Checker,
) -> None:
    library = tmp_path / "library.py"
    library.write_text(LIBRARY_SOURCE, encoding="utf-8")
    (tmp_path / "external.pyi").write_text(
        "class Parser[T]: ...\n",
        encoding="utf-8",
    )
    consumer = tmp_path / "consumer.py"
    consumer.write_text(CONSUMER_SOURCE, encoding="utf-8")

    generated = generate_module(library, maximum_arity=3)
    assert isinstance(generated, Success)
    library.with_suffix(".pyi").write_text(generated.unwrap().content, encoding="utf-8")

    completed = run(
        (*checker.arguments, consumer.name),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


CLASS_LIBRARY_SOURCE = """
from dataclasses import dataclass
from typing import Protocol, dataclass_transform

from typeforge import Collect, Each


class Entity(Protocol):
    def __hash__(self) -> int: ...


@dataclass(frozen=True)
class Group[E: Entity]:
    entities: set[E]

    def bundle[*Ts](self, *values: Each[Ts]) -> Collect[Ts]:
        raise NotImplementedError
""".lstrip()


CLASS_CONSUMER_SOURCE = """
from typing import assert_type

from classes import Group


class Item:
    pass


group = Group[Item]({Item()})
assert_type(group.bundle(1, "two"), tuple[int, str])
""".lstrip()


@pytest.mark.parametrize("checker", CHECKERS, ids=lambda checker: checker.name)
def test_generated_class_stub_is_consumed_by_existing_checkers(
    tmp_path: Path,
    checker: Checker,
) -> None:
    library = tmp_path / "classes.py"
    library.write_text(CLASS_LIBRARY_SOURCE, encoding="utf-8")
    consumer = tmp_path / "class_consumer.py"
    consumer.write_text(CLASS_CONSUMER_SOURCE, encoding="utf-8")

    generated = generate_module(library, maximum_arity=3)
    assert isinstance(generated, Success)
    library.with_suffix(".pyi").write_text(generated.unwrap().content, encoding="utf-8")

    completed = run(
        (*checker.arguments, consumer.name),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


STRUCTURAL_MAP_LIBRARY_SOURCE = """
from dataclasses import dataclass, field
from typing import Protocol, dataclass_transform

from typeforge import Case, Collect, Default, Each, Map, Value


class Component(Protocol):
    def __hash__(self) -> int: ...


class Entity(Protocol):
    def __hash__(self) -> int: ...


@dataclass(frozen=True)
class Option[T]:
    value: T


type QueryResult[T] = Map[
    T,
    Case[Option[Value], Value | None],
    Default[T],
]


class World[E: Entity]:
    entities: list[E] = field(default_factory=list)

    def query[T](
        self,
        *components: Each[type[T]],
    ) -> tuple[E, *Collect[QueryResult[T]]] | None:
        raise NotImplementedError


@dataclass_transform(frozen_default=True)
def component[T](value: type[T]) -> type[T]:
    return value


@component
class Position:
    pass


@component
class Velocity:
    pass
""".lstrip()


STRUCTURAL_MAP_CONSUMER_SOURCE = """
from typing import assert_type

from ecs import Option, Position, Velocity, World

world = World[int]()
assert_type(
    world.query(Position, Velocity),
    tuple[int, Position, Velocity] | None,
)
assert_type(
    world.query(Position, Option[Velocity]),
    tuple[int, Position, Velocity | None] | None,
)
assert_type(
    world.query(Position, Velocity, Position),
    tuple[int, *tuple[object, ...]] | None,
)
""".lstrip()


STRUCTURAL_MAP_MARKER_STUB = """
type Case[Input, Output] = Output
type Collect[T] = tuple[T, ...]
type Default[Output] = Output
type Each[T] = T
type Map[Subject, *Cases] = object
type Value = object
""".lstrip()


@pytest.mark.parametrize("checker", CHECKERS, ids=lambda checker: checker.name)
def test_generated_structural_map_stub_is_consumed_by_existing_checkers(
    tmp_path: Path,
    checker: Checker,
) -> None:
    library = tmp_path / "ecs.py"
    library.write_text(STRUCTURAL_MAP_LIBRARY_SOURCE, encoding="utf-8")
    consumer = tmp_path / "ecs_consumer.py"
    consumer.write_text(STRUCTURAL_MAP_CONSUMER_SOURCE, encoding="utf-8")
    (tmp_path / "typeforge.pyi").write_text(
        STRUCTURAL_MAP_MARKER_STUB,
        encoding="utf-8",
    )

    authored = run(
        (*checker.arguments, library.name),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert authored.returncode == 0, authored.stdout + authored.stderr

    generated = generate_module(library, maximum_arity=2)
    assert isinstance(generated, Success)
    library.with_suffix(".pyi").write_text(generated.unwrap().content, encoding="utf-8")

    completed = run(
        (*checker.arguments, consumer.name),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        generated.unwrap().content + completed.stdout + completed.stderr
    )
