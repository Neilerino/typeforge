"""Production corrections from the deferred Map characterization matrix."""

from pathlib import Path

import pytest
from returns.result import Failure

from typeforge.compiler.adaptation import AdaptationError
from typeforge.compiler.pipeline import generate_module


def test_parameterized_types_remain_assignable_to_object(tmp_path: Path) -> None:
    path = tmp_path / "schemas.py"
    path.write_text(
        """from typeforge._markers import Assignable
from typeforge import Map
from typeforge.pydantic import Schema
class Payload:
    value: Schema[Map[int, Assignable[list[int], object] : str, ... : bytes]]
"""
    )

    assert generate_module(path, maximum_arity=1).unwrap().content == (
        "class Payload:\n    value: str\n"
    )


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        pytest.param(
            "Map[T, int : str, ... : bytes]",
            "str | bytes",
            id="C1-unknown-exact",
        ),
        pytest.param(
            "Map[T, U : str, ... : bytes]",
            "str | bytes",
            id="C2-different-symbols",
        ),
        pytest.param(
            "Map[T, Equal[T, T] : str, ... : bytes]",
            "str",
            id="C3-same-symbol-equal",
        ),
        pytest.param(
            "Map[T, Assignable[T, T] : str, ... : bytes]",
            "str",
            id="C4-same-symbol-assignable",
        ),
        pytest.param(
            "Map[list[T], list[int] : str, ... : bytes]",
            "str | bytes",
            id="C5-unknown-subject-argument",
        ),
        pytest.param(
            "Map[list[int], list[T] : str, ... : bytes]",
            "str | bytes",
            id="C6-unknown-pattern-argument",
        ),
        pytest.param(
            "Map[int, Equal[tuple[int, T], tuple[str, int]] : str, ... : bytes]",
            "bytes",
            id="C7-known-argument-mismatch",
        ),
        pytest.param(
            "Map[tuple[int, T], tuple[Item, Item] : Item, ... : bytes]",
            "int | bytes",
            id="C8-repeated-capture",
        ),
        pytest.param(
            "Map[int, Equal[Map[T, T : int, ... : str], int] : bytes, ... : float]",
            "bytes",
            id="C9-nested-definite-predicate",
        ),
    ],
)
def test_generic_schema_corrections(
    tmp_path: Path, expression: str, expected: str
) -> None:
    path = tmp_path / "schemas.py"
    path.write_text(
        "from typeforge._markers import Equal, Assignable\n"
        "from typeforge import Capture, Map\n"
        "from typeforge.pydantic import Schema\n"
        'Item = Capture("Item")\n'
        "class Payload[T, U]:\n"
        f"    value: Schema[{expression}]\n"
    )

    generated = generate_module(path, maximum_arity=1).unwrap()
    assert (
        generated.content
        == f"Item: object\n\nclass Payload[T, U]:\n    value: {expected}\n"
    )


def test_selected_alias_output_expands_nested_aliases(tmp_path: Path) -> None:
    path = tmp_path / "schemas.py"
    path.write_text(
        """from typeforge import Map
from typeforge.pydantic import Schema
type Inner[A] = Map[A, int : str, ... : bytes]
type Outer[A] = Map[A, int : Inner[A], ... : float]
class Payload:
    value: Schema[Outer[int]]
"""
    )

    generated = generate_module(path, maximum_arity=1).unwrap()
    assert generated.content == (
        "type Inner[A] = object\n\ntype Outer[A] = object\n\n"
        "class Payload:\n    value: str\n"
    )


@pytest.mark.parametrize(
    ("aliases", "use", "cycle"),
    [
        (
            """type First[A] = Map[A, int : Second[A], ... : A]
type Second[A] = Map[A, int : First[A], ... : A]
""",
            "First[int]",
            "First -> Second -> First",
        ),
        (
            "type Loop[A] = Map[A, int : Loop[A], ... : A]\n",
            "Loop[int]",
            "Loop -> Loop",
        ),
    ],
    ids=["C11-cross-alias-cycle", "C12-self-cycle"],
)
def test_schema_alias_cycles_report_authored_paths(
    tmp_path: Path, aliases: str, use: str, cycle: str
) -> None:
    path = tmp_path / "schemas.py"
    path.write_text(
        "from typeforge import Map\n"
        "from typeforge.pydantic import Schema\n"
        f"{aliases}"
        f"class Payload:\n    value: Schema[{use}]\n"
    )

    assert generate_module(path, maximum_arity=1) == Failure(
        AdaptationError("Payload", f"Schema[{use}]", f"cyclic schema alias: {cycle}")
    )


def test_literal_type_output_in_a_transformed_schema_record(tmp_path: Path) -> None:
    path = tmp_path / "schemas.py"
    path.write_text(
        """from typing import TypedDict, Literal
from typeforge import Map, Field, Fields, Record
from typeforge.pydantic import Schema


class Row(TypedDict):
    original: int


type Transform[T] = Record(
    (
        Field(
            name=field.name,
            type=Map[field.type, int : Literal["accepted"], ...:bytes])
        for field in Fields[T]
    )
)


class Payload:
    value: Schema[Transform[Row]]
"""
    )

    generated = generate_module(path, maximum_arity=1).unwrap()
    assert (
        "class Transform_Row(tf_typing.TypedDict):\n"
        '    original: Literal["accepted"]\n' in generated.content
    )
    assert generated.content.endswith("class Payload:\n    value: Transform_Row\n")
