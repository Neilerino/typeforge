"""Retained production behavior for deferred-input roadmap slice 1.

Case IDs retain the deferred Input Map characterization witnesses below.
Intended corrections live in that matrix until their owning slice is implemented.
"""

from pathlib import Path
from textwrap import dedent

from pytest import mark, param
from returns.result import Success

from typeforge.compiler.pipeline import generate_module


@mark.parametrize(
    ("annotation", "expected"),
    (
        param(
            "Map[list[int], list[Value] : set[Value], ... : bytes]",
            "set[int]",
            id="direct-structural",
        ),
        param(
            'Map[int, int : Literal["accepted"], ... : Literal["rejected"]]',
            'Literal["accepted"]',
            id="literal-output",
        ),
        param(
            'Map[bytes, int : str, ... : Literal["rejected"]]',
            'Literal["rejected"]',
            id="literal-default",
        ),
        param(
            'Map[Literal["yes"], Literal["yes"] : str, ... : bytes]',
            "str",
            id="literal-case",
        ),
        param(
            'Map[int, Equal[Literal["yes"], Literal["yes"]] : str, ... : bytes]',
            "str",
            id="literal-predicate",
        ),
        param(
            'Map[int, Assignable[Literal["yes"], Literal["yes"]] : str, ... : bytes]',
            "str",
            id="literal-assignable",
        ),
        param(
            "Map[list[int], list[Value] : set[Value] | None, ... : bytes]",
            "set[int] | None",
            id="union-output",
        ),
        param(
            "Map[list[int], list[Value] : tuple[Value | None], ... : bytes]",
            "tuple[int | None]",
            id="nested-union-output",
        ),
        param(
            "Map[int | bytes, int : str, ... : float]",
            "str | float",
            id="union-subject",
        ),
        param(
            "Map[list[int | int], list[int] : str, ... : bytes]",
            "str",
            id="normalized-subject",
        ),
        param(
            "Map[list[int], list[int | int] : str, ... : bytes]",
            "str",
            id="normalized-pattern",
        ),
        param(
            "Map[list[int], list[Value] : tuple[Value | int], ... : bytes]",
            "tuple[int]",
            id="normalized-output",
        ),
        param(
            "list[Map[int, int : str, ... : bytes]]",
            "list[str]",
            id="under-application",
        ),
        param(
            "Map[int, int : str, ... : bytes] | None",
            "str | None",
            id="under-union",
        ),
        param(
            "tuple[*Map[int, int : tuple[str, bytes], ... : tuple[float]]]",
            "tuple[*tuple[str, bytes]]",
            id="under-starred",
        ),
        param(
            "tuple[Schema[Map[int, int : str, ... : bytes]], int]",
            "tuple[str, int]",
            id="nested-schema",
        ),
        param(
            (
                "Map[list[int], list[Value] : Map[Value, int : str, ..."
                " : bytes], ... : float]"
            ),
            "str",
            id="nested-capture-map",
        ),
        param("Map[Input, int : int, str : bytes]", "int | bytes", id="deferred"),
        param(
            "Map[Input, Equal[Input, str] : int, ... : float]",
            "int | float",
            id="deferred-predicate",
        ),
        param(
            "Map[Input, int : Map[Input, int : str, ... : float], ... : bytes]",
            "str | float | bytes",
            id="nested-deferred",
        ),
        param(
            "Map[int | str, int : Map[Input, int : bytes, ... : float], ... : bytes]",
            "bytes | float",
            id="union-deferred-outputs",
        ),
        param(
            "Map[Input, int : str, str : str, ... : str]",
            "str",
            id="duplicate-deferred",
        ),
        param(
            "Map[Input, int : str, ... : Never]",
            "str",
            id="deferred-explicit-never",
        ),
        param("Map[Input, int : str]", "str", id="deferred-omitted"),
        param("Map[str, int : str]", "Never", id="no-match-omitted"),
        param(
            "Map[str, int : str, ... : Never]",
            "Never",
            id="no-match-explicit-never",
        ),
        param("Map[int | bytes, int : str]", "str", id="union-no-match"),
        param(
            "Map[Input, int : Never, ... : Never]",
            "Never",
            id="deferred-all-never",
        ),
    ),
)
def test_schema_maps_preserve_type_outputs(
    tmp_path: Path, annotation: str, expected: str
) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from typing import Literal, Never\n"
        "from typeforge import Map, Value\n"
        "from typeforge._markers import All, Any, Assignable, Equal, Not\n"
        "from typeforge.pydantic import Input, Schema\n\n"
        "class Payload:\n"
        f"    value: Schema[{annotation}]\n",
        encoding="utf-8",
    )

    generated = generate_module(path, maximum_arity=1)

    assert isinstance(generated, Success)
    assert generated.unwrap().content == (
        f"from typing import Literal, Never\n\nclass Payload:\n    value: {expected}\n"
    )


@mark.parametrize(
    ("annotation", "expected"),
    (
        param(
            "Map[T, Equal[T, int] : str, ... : bytes]",
            "str | bytes",
            id="unknown-predicate",
        ),
        param(
            "Map[T, Assignable[T, int] : str, ... : bytes]",
            "str | bytes",
            id="unknown-assignable",
        ),
        param(
            "Map[int, Equal[int, int] : float, Equal[T, int] : str, ... : bytes]",
            "float",
            id="known-true-first",
        ),
        param(
            "Map[int, Equal[int, str] : float, Equal[T, int] : str, ... : bytes]",
            "str | bytes",
            id="known-false-first",
        ),
        param(
            "Map[int, int : float, Equal[T, int] : str, ... : bytes]",
            "float",
            id="exact-first",
        ),
        param(
            "Map[int, Equal[T, int] : str, Equal[U, int] : float, ... : bytes]",
            "str | float | bytes",
            id="unknown-then-unknown",
        ),
        param(
            (
                "Map[int, Equal[T, int] : str, int : float, Equal[U, "
                "int] : complex, ... : bytes]"
            ),
            "str | float",
            id="unknown-then-match",
        ),
        param("Map[int, Equal[T, int] : str]", "str", id="unknown-no-default"),
        param("Map[T, T : str, ... : bytes]", "str", id="same-symbol-exact"),
        param(
            "Map[list[T], list[T] : str, ... : bytes]",
            "str",
            id="same-structure",
        ),
        param(
            "Map[list[T], set[int] : str, ... : bytes]",
            "bytes",
            id="known-origin-mismatch",
        ),
        param(
            "Map[tuple[int, T], tuple[str, int] : float, ... : bytes]",
            "bytes",
            id="known-argument-mismatch",
        ),
        param(
            "Map[tuple[T, int], tuple[str, bytes] : float, ... : bytes]",
            "bytes",
            id="known-argument-mismatch-after-unknown",
        ),
        param(
            "Map[tuple[T, T], tuple[Value, Value] : Value, ... : bytes]",
            "T",
            id="repeated-capture-same",
        ),
        param(
            "Map[tuple[int, str, T], tuple[Value, Value, Value] : Value, ... : bytes]",
            "bytes",
            id="repeated-capture-mismatch",
        ),
        param(
            "Map[int, int : Map[T, Equal[T, int] : str, ... : bytes], ... : float]",
            "str | bytes",
            id="nested-uncertain-output",
        ),
        param(
            "Map[T, Equal[T, int] : Map[Input, int : str, ... : float], ... : bytes]",
            "str | float | bytes",
            id="uncertain-deferred-output",
        ),
        param(
            "Map[int, Equal[Map[T, int : int, ... : str], int] : bytes, ... : float]",
            "bytes | float",
            id="nested-uncertain-predicate",
        ),
        param(
            "Map[int, All[Equal[T, int], Equal[int, str]] : str, ... : bytes]",
            "bytes",
            id="all-unknown-false",
        ),
        param(
            "Map[int, Any[Equal[T, int], Equal[int, int]] : str, ... : bytes]",
            "str",
            id="any-unknown-true",
        ),
        param(
            "Map[int, Not[Equal[T, int]] : str, ... : bytes]",
            "str | bytes",
            id="not-unknown",
        ),
    ),
)
def test_generic_schema_maps_preserve_reachable_outputs(
    tmp_path: Path, annotation: str, expected: str
) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from typing import Literal, Never\n"
        "from typeforge import Map, Value\n"
        "from typeforge._markers import All, Any, Assignable, Equal, Not\n"
        "from typeforge.pydantic import Input, Schema\n\n"
        "class Payload[T, U]:\n"
        f"    value: Schema[{annotation}]\n",
        encoding="utf-8",
    )

    generated = generate_module(path, maximum_arity=1)

    assert isinstance(generated, Success)
    assert generated.unwrap().content == (
        "from typing import Literal, Never\n\n"
        "class Payload[T, U]:\n"
        f"    value: {expected}\n"
    )


@mark.parametrize(
    ("aliases", "annotation", "expected"),
    (
        param(
            "type Structural[A] = Map[A, list[Value] : set[Value], ... : bytes]",
            "Structural[list[int]]",
            "set[int]",
            id="structural-alias",
        ),
        param(
            "type Wire[A] = Map[A, Equal[A, int] : str, ... : bytes]",
            "Wire[T]",
            "str | bytes",
            id="generic-alias",
        ),
        param(
            "type Wire[A] = Map[A, int : str]",
            "Wire[bytes]",
            "Never",
            id="alias-omitted",
        ),
        param(
            "type Wire[A] = Map[A, int : str, ... : Never]",
            "Wire[bytes]",
            "Never",
            id="alias-explicit-never",
        ),
        param(
            """type Inner[A] = Map[A, int : str, ... : bytes]
type Outer[A] = Map[A, str : float, ... : complex]""",
            "Outer[Inner[int]]",
            "float",
            id="alias-in-argument",
        ),
        param(
            "type Wire[A] = Map[A, int : str, ... : bytes]",
            "list[Wire[int]]",
            "list[str]",
            id="alias-under-application",
        ),
        param(
            "type Wire[A] = Map[A, int : str, ... : bytes]",
            "Wire[int] | None",
            "str | None",
            id="alias-under-union",
        ),
        param(
            "type Wire[A] = Map[A, int : tuple[str, bytes], ... : tuple[float]]",
            "tuple[*Wire[int]]",
            "tuple[*tuple[str, bytes]]",
            id="alias-under-starred",
        ),
        param(
            "type Wire[A] = Map[A, int : str, ... : bytes]",
            "tuple[Schema[Wire[int]], int]",
            "tuple[str, int]",
            id="alias-under-schema",
        ),
    ),
)
def test_schema_relationship_aliases_preserve_type_outputs(
    tmp_path: Path, aliases: str, annotation: str, expected: str
) -> None:
    path = tmp_path / "aliases.py"
    path.write_text(
        "from typing import Never\n"
        "from typeforge._markers import Equal\nfrom typeforge import Map, Value\n"
        "from typeforge.pydantic import Schema\n\n"
        f"{aliases}\n\n"
        "class Payload[T]:\n"
        f"    value: Schema[{annotation}]\n",
        encoding="utf-8",
    )

    generated = generate_module(path, maximum_arity=1)

    assert isinstance(generated, Success)
    content = generated.unwrap().content
    assert content.endswith(f"class Payload[T]:\n    value: {expected}\n")
    # Publication keeps relationship declarations conservative even when a
    # concrete schema use of the same alias can select a precise output.
    published_aliases = tuple(
        line for line in content.splitlines() if line.startswith("type ")
    )
    assert published_aliases == tuple(
        f"{declaration.split(' = ', 1)[0]} = object"
        for declaration in aliases.splitlines()
    )


@mark.parametrize(
    ("transform", "expected_field"),
    (
        param(
            'Field[Literal["renamed"], Value]',
            "renamed: int",
            id="literal-field-name",
        ),
        param(
            (
                'Field[Map[Key, Literal["original"] : '
                'Literal["renamed"], ... : Key], Value]'
            ),
            "renamed: int",
            id="literal-field-name-case",
        ),
        param(
            (
                'Field[Map[Key, Equal[Key, Literal["original"]] : '
                'Literal["renamed"], ... : Key], Value]'
            ),
            "renamed: int",
            id="literal-field-name-predicate",
        ),
        param(
            "Field[Key, Map[Value, str : str]]",
            "original: tf_typing.Never",
            id="field-value-never",
        ),
    ),
)
def test_schema_field_transforms_preserve_typing_emission(
    tmp_path: Path, transform: str, expected_field: str
) -> None:
    path = tmp_path / "records.py"
    path.write_text(
        "from typing import Literal, TypedDict\n"
        "from typeforge import Field, Key, Map, MapFields, Value\n"
        "from typeforge._markers import Equal\n"
        "from typeforge.pydantic import Schema\n\n"
        "class Record(TypedDict):\n"
        "    original: int\n\n"
        f"type Transform[T] = MapFields[T, {transform}]\n\n"
        "class Payload:\n"
        "    value: Schema[Transform[Record]]\n",
        encoding="utf-8",
    )

    generated = generate_module(path, maximum_arity=1)

    assert isinstance(generated, Success)
    assert generated.unwrap().content == dedent(f"""\
        import typing as tf_typing
        from typing import Literal, TypedDict

        class Record(tf_typing.TypedDict):
            original: int

        class Transform_Record(tf_typing.TypedDict):
            {expected_field}

        type Transform[T] = object

        class Payload:
            value: Transform_Record
        """)
