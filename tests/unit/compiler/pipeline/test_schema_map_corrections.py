"""Production corrections from the deferred Map characterization matrix."""

from pathlib import Path

import pytest
from returns.result import Failure

from typeforge.compiler.adaptation import AdaptationError
from typeforge.compiler.pipeline import generate_module


def test_parameterized_types_remain_assignable_to_object(tmp_path: Path) -> None:
    path = tmp_path / "schemas.py"
    path.write_text(
        "from typeforge import Map, Case, Default, Assignable\n"
        "from typeforge.pydantic import Schema\n"
        "class Payload:\n"
        "    value: Schema[Map[int, Case[Assignable[list[int], object], str], "
        "Default[bytes]]]\n"
    )

    assert generate_module(path, maximum_arity=1).unwrap().content == (
        "class Payload:\n    value: str\n"
    )


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        pytest.param(
            "Map[T, Case[int, str], Default[bytes]]",
            "str | bytes",
            id="C1-unknown-exact",
        ),
        pytest.param(
            "Map[T, Case[U, str], Default[bytes]]",
            "str | bytes",
            id="C2-different-symbols",
        ),
        pytest.param(
            "Map[T, Case[Equal[T, T], str], Default[bytes]]",
            "str",
            id="C3-same-symbol-equal",
        ),
        pytest.param(
            "Map[T, Case[Assignable[T, T], str], Default[bytes]]",
            "str",
            id="C4-same-symbol-assignable",
        ),
        pytest.param(
            "Map[list[T], Case[list[int], str], Default[bytes]]",
            "str | bytes",
            id="C5-unknown-subject-argument",
        ),
        pytest.param(
            "Map[list[int], Case[list[T], str], Default[bytes]]",
            "str | bytes",
            id="C6-unknown-pattern-argument",
        ),
        pytest.param(
            "Map[int, Case[Equal[tuple[int, T], tuple[str, int]], str], "
            "Default[bytes]]",
            "bytes",
            id="C7-known-argument-mismatch",
        ),
        pytest.param(
            "Map[tuple[int, T], Case[tuple[Value, Value], Value], Default[bytes]]",
            "int | bytes",
            id="C8-repeated-capture",
        ),
        pytest.param(
            "Map[int, Case[Equal[Map[T, Case[T, int], Default[str]], int], bytes], "
            "Default[float]]",
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
        "from typeforge import Map, Case, Default, Equal, Assignable, Value\n"
        "from typeforge.pydantic import Schema\n"
        "class Payload[T, U]:\n"
        f"    value: Schema[{expression}]\n"
    )

    generated = generate_module(path, maximum_arity=1).unwrap()
    assert generated.content == f"class Payload[T, U]:\n    value: {expected}\n"


def test_selected_alias_output_expands_nested_aliases(tmp_path: Path) -> None:
    path = tmp_path / "schemas.py"
    path.write_text(
        "from typeforge import Map, Case, Default\n"
        "from typeforge.pydantic import Schema\n"
        "type Inner[A] = Map[A, Case[int, str], Default[bytes]]\n"
        "type Outer[A] = Map[A, Case[int, Inner[A]], Default[float]]\n"
        "class Payload:\n"
        "    value: Schema[Outer[int]]\n"
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
            "type First[A] = Map[A, Case[int, Second[A]], Default[A]]\n"
            "type Second[A] = Map[A, Case[int, First[A]], Default[A]]\n",
            "First[int]",
            "First -> Second -> First",
        ),
        (
            "type Loop[A] = Map[A, Case[int, Loop[A]], Default[A]]\n",
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
        "from typeforge import Map, Case, Default\n"
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
        "from typing import TypedDict, Literal\n"
        "from typeforge import Map, MapFields, Case, Default, Field, Key, Value\n"
        "from typeforge.pydantic import Schema\n"
        "class Record(TypedDict):\n    original: int\n"
        "type Transform[T] = MapFields[T, Field[Key, Map[Value, "
        'Case[int, Literal["accepted"]], Default[bytes]]]]\n'
        "class Payload:\n    value: Schema[Transform[Record]]\n"
    )

    generated = generate_module(path, maximum_arity=1).unwrap()
    assert (
        "class Transform_Record(tf_typing.TypedDict):\n"
        '    original: Literal["accepted"]\n' in generated.content
    )
    assert generated.content.endswith("class Payload:\n    value: Transform_Record\n")
