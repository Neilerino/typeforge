from pathlib import Path

import pytest
from returns.result import Failure

from typeforge.compiler.adaptation import AdaptationError, expand_schema_aliases
from typeforge.compiler.pipeline import compile_source, generate_module
from typeforge.compiler.source import (
    MapMarker,
    MarkerTypeExpression,
    normalize_marker,
    parse_source,
)


def test_predicate_alias_declarations_and_consuming_maps_compile(
    tmp_path: Path,
) -> None:
    path = tmp_path / "example.py"
    path.write_text("""from typeforge._markers import Assignable
from typeforge import Map
from typeforge.pydantic import Schema
type Numeric = Assignable[int]
class Payload:
    value: Schema[Map[int, Numeric: str, ...: bytes]]
def select[T](value: T) -> Map[T, Numeric: str, ...: bytes]: ...
""")
    content = generate_module(path, maximum_arity=2).unwrap().content
    assert "type Numeric = bool" in content
    assert "value: str" in content
    assert "def select(value: int) -> str" in content


def test_generic_compound_aliases_keep_nested_subjects_and_explicit_operands(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested.py"
    path.write_text("""from typeforge._markers import All, Any, Not, Equal, Assignable
from typeforge import Map
from typeforge.pydantic import Schema
type Is[T] = Equal[T]
type Alias[T] = Is[T]
type Numeric = All[Assignable[int], Not[Alias[bool]]]
type Either = Any[Alias[int], Alias[bytes]]
type Explicit[T] = Equal[T, bytes]
type Selected[T] = Map[T, Numeric: Map[bytes, Either: str, ...: float], ...: bytes]
class Payload:
    first: Schema[Selected[int]]
    second: Schema[Selected[bool]]
    explicit: Schema[Map[int, Explicit[bytes]: str, ...: float]]
""")
    content = generate_module(path, maximum_arity=2).unwrap().content
    assert "first: str" in content
    assert "second: bytes" in content
    assert "explicit: str" in content


@pytest.mark.parametrize("subject", ["int", "str", "bool", "int | str"])
def test_union_predicate_alias_has_inline_schema_behavior(
    subject: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / "unions.py"
    path.write_text(f"""\
from typeforge import Map
from typeforge._markers import Assignable
from typeforge.pydantic import Schema
type Numeric = Assignable[int | str]
class Payload:
    aliased: Schema[Map[{subject}, Numeric: bytes | None, ...: float]]
    inline: Schema[Map[{subject}, Assignable[int | str]: bytes | None, ...: float]]
""")
    content = generate_module(path, maximum_arity=2).unwrap().content
    fields = dict(
        line.strip().split(": ", 1)
        for line in content.splitlines()
        if line.strip().startswith(("aliased:", "inline:"))
    )
    assert fields["aliased"] == fields["inline"]


@pytest.mark.parametrize(
    "use", ["Numeric", "Map[int, int: Numeric]", "Map[int, Equal[Numeric, int]: str]"]
)
def test_unbound_aliases_fail_outside_selectors(use: str) -> None:
    result = compile_source(
        f"""\
from typeforge import Map
from typeforge._markers import Equal, Assignable
from typeforge.pydantic import Schema
type Numeric = Assignable[int]
class Payload:
    value: Schema[{use}]
""",
        Path("unbound.py"),
        maximum_arity=2,
    )
    assert isinstance(result, Failure)
    assert "Assignable requires two type arguments" in str(result.failure())


@pytest.mark.parametrize(
    ("definition", "use", "message"),
    [
        ("type Is[T] = Equal[T]", "Is", "requires 1 type argument"),
        ("type Is[*Ts] = Equal[int]", "Is[int]", "ordinary type parameters"),
        ("type Is = All[Equal[int], Is]", "Is", "cyclic schema alias"),
        ('type Is = Equal["text"]', "Is", "Literal"),
        ("type Is = Equal[int, str, bytes]", "Is", "two type arguments"),
    ],
)
def test_unsupported_predicate_aliases_are_authored_failures(
    definition: str,
    use: str,
    message: str,
) -> None:
    result = compile_source(
        f"""\
from typeforge import Map
from typeforge._markers import All, Equal
{definition}
def select[T](value: T) -> Map[T, {use}: str]: ...
""",
        Path("bad.py"),
        maximum_arity=2,
    )
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, AdaptationError)
    assert message in error.message
    assert error.declaration in {"Is", "select"}


def test_expanded_predicate_retains_authored_span_and_subject_identity() -> None:
    source = (
        parse_source(
            """from typeforge._markers import Equal
from typeforge import Map
type Is[T] = Equal[T]
type Selected = Map[bytes, Is[int]: str]
""",
            Path("origins.py"),
        )
        .unwrap()
        .source
    )
    expanded = expand_schema_aliases(
        source.aliases[1].value, source.aliases, declaration="Selected"
    ).unwrap()
    assert isinstance(expanded, MarkerTypeExpression)
    marker = normalize_marker(expanded)
    assert isinstance(marker, MapMarker)
    predicate = marker.entries[0].test
    assert isinstance(predicate, MarkerTypeExpression)
    assert predicate.span == source.aliases[0].value.span
    assert predicate.source == "Equal[T]"
    assert predicate.arguments[0] is marker.subject
    assert predicate.arguments[1].source == "int"


def test_alias_binding_works_with_field_subjects_without_executing_source(
    tmp_path: Path,
) -> None:
    path = tmp_path / "records.py"
    path.write_text("""\
from typing import TypedDict, Literal
from typeforge import Map, Field, Fields, Record
from typeforge._markers import Equal

type Name = Equal[Literal["value"]]
type Integer = Equal[int]


class Row(TypedDict):
    value: int


type Selected[T] = Record(
    (
        Map[
            field.name,
            Name : Field[field.name, Map[field.type, Integer:str, ...:bytes]],
        ]
        for field in Fields[T]
    )
)


def transform(row: Row) -> Selected[Row]: ...


_tripwire: int = 1 // 0
""")
    assert "value: str" in generate_module(path, maximum_arity=2).unwrap().content
