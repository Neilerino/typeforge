"""Retained production behavior for deferred-input roadmap slice 1.

Case IDs are indexed by docs/in_progress_tasks/deferred-input-map-characterization.md.
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
            "Map[list[int], Case[list[Value], set[Value]], Default[bytes]]",
            "set[int]",
            id="direct-structural",
        ),
        param(
            'Map[int, Case[int, Literal["accepted"]], Default[Literal["rejected"]]]',
            'Literal["accepted"]',
            id="literal-output",
        ),
        param(
            'Map[bytes, Case[int, str], Default[Literal["rejected"]]]',
            'Literal["rejected"]',
            id="literal-default",
        ),
        param(
            'Map[Literal["yes"], Case[Literal["yes"], str], Default[bytes]]',
            "str",
            id="literal-case",
        ),
        param(
            'Map[int, Case[Equal[Literal["yes"], Literal["yes"]], str], '
            "Default[bytes]]",
            "str",
            id="literal-predicate",
        ),
        param(
            'Map[int, Case[Assignable[Literal["yes"], Literal["yes"]], str], '
            "Default[bytes]]",
            "str",
            id="literal-assignable",
        ),
        param(
            "Map[list[int], Case[list[Value], set[Value] | None], Default[bytes]]",
            "set[int] | None",
            id="union-output",
        ),
        param(
            "Map[list[int], Case[list[Value], tuple[Value | None]], Default[bytes]]",
            "tuple[int | None]",
            id="nested-union-output",
        ),
        param(
            "Map[int | bytes, Case[int, str], Default[float]]",
            "str | float",
            id="union-subject",
        ),
        param(
            "Map[list[int | int], Case[list[int], str], Default[bytes]]",
            "str",
            id="normalized-subject",
        ),
        param(
            "Map[list[int], Case[list[int | int], str], Default[bytes]]",
            "str",
            id="normalized-pattern",
        ),
        param(
            "Map[list[int], Case[list[Value], tuple[Value | int]], Default[bytes]]",
            "tuple[int]",
            id="normalized-output",
        ),
        param(
            "list[Map[int, Case[int, str], Default[bytes]]]",
            "list[str]",
            id="under-application",
        ),
        param(
            "Map[int, Case[int, str], Default[bytes]] | None",
            "str | None",
            id="under-union",
        ),
        param(
            "tuple[*Map[int, Case[int, tuple[str, bytes]], Default[tuple[float]]]]",
            "tuple[*tuple[str, bytes]]",
            id="under-starred",
        ),
        param(
            "tuple[Schema[Map[int, Case[int, str], Default[bytes]]], int]",
            "tuple[str, int]",
            id="nested-schema",
        ),
        param(
            "Map[list[int], Case[list[Value], "
            "Map[Value, Case[int, str], Default[bytes]]], Default[float]]",
            "str",
            id="nested-capture-map",
        ),
        param(
            "Map[Input, Case[int, int], Case[str, bytes]]", "int | bytes", id="deferred"
        ),
        param(
            "Map[Input, Case[Equal[Input, str], int], Default[float]]",
            "int | float",
            id="deferred-predicate",
        ),
        param(
            "Map[Input, Case[int, Map[Input, Case[int, str], Default[float]]], "
            "Default[bytes]]",
            "str | float | bytes",
            id="nested-deferred",
        ),
        param(
            "Map[int | str, Case[int, "
            "Map[Input, Case[int, bytes], Default[float]]], Default[bytes]]",
            "bytes | float",
            id="union-deferred-outputs",
        ),
        param(
            "Map[Input, Case[int, str], Case[str, str], Default[str]]",
            "str",
            id="duplicate-deferred",
        ),
        param(
            "Map[Input, Case[int, str], Default[Never]]",
            "str",
            id="deferred-explicit-never",
        ),
        param("Map[Input, Case[int, str]]", "str", id="deferred-omitted"),
        param("Map[str, Case[int, str]]", "Never", id="no-match-omitted"),
        param(
            "Map[str, Case[int, str], Default[Never]]",
            "Never",
            id="no-match-explicit-never",
        ),
        param("Map[int | bytes, Case[int, str]]", "str", id="union-no-match"),
        param(
            "Map[Input, Case[int, Never], Default[Never]]",
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
        "from typeforge import (\n"
        "    All, Any, Assignable, Case, Default, Equal, Map, Not, Value,\n"
        ")\n"
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
            "Map[T, Case[Equal[T, int], str], Default[bytes]]",
            "str | bytes",
            id="unknown-predicate",
        ),
        param(
            "Map[T, Case[Assignable[T, int], str], Default[bytes]]",
            "str | bytes",
            id="unknown-assignable",
        ),
        param(
            "Map[int, Case[Equal[int, int], float], "
            "Case[Equal[T, int], str], Default[bytes]]",
            "float",
            id="known-true-first",
        ),
        param(
            "Map[int, Case[Equal[int, str], float], "
            "Case[Equal[T, int], str], Default[bytes]]",
            "str | bytes",
            id="known-false-first",
        ),
        param(
            "Map[int, Case[int, float], Case[Equal[T, int], str], Default[bytes]]",
            "float",
            id="exact-first",
        ),
        param(
            "Map[int, Case[Equal[T, int], str], "
            "Case[Equal[U, int], float], Default[bytes]]",
            "str | float | bytes",
            id="unknown-then-unknown",
        ),
        param(
            "Map[int, Case[Equal[T, int], str], Case[int, float], "
            "Case[Equal[U, int], complex], Default[bytes]]",
            "str | float",
            id="unknown-then-match",
        ),
        param("Map[int, Case[Equal[T, int], str]]", "str", id="unknown-no-default"),
        param("Map[T, Case[T, str], Default[bytes]]", "str", id="same-symbol-exact"),
        param(
            "Map[list[T], Case[list[T], str], Default[bytes]]",
            "str",
            id="same-structure",
        ),
        param(
            "Map[list[T], Case[set[int], str], Default[bytes]]",
            "bytes",
            id="known-origin-mismatch",
        ),
        param(
            "Map[tuple[int, T], Case[tuple[str, int], float], Default[bytes]]",
            "bytes",
            id="known-argument-mismatch",
        ),
        param(
            "Map[tuple[T, int], Case[tuple[str, bytes], float], Default[bytes]]",
            "bytes",
            id="known-argument-mismatch-after-unknown",
        ),
        param(
            "Map[tuple[T, T], Case[tuple[Value, Value], Value], Default[bytes]]",
            "T",
            id="repeated-capture-same",
        ),
        param(
            "Map[tuple[int, str, T], "
            "Case[tuple[Value, Value, Value], Value], Default[bytes]]",
            "bytes",
            id="repeated-capture-mismatch",
        ),
        param(
            "Map[int, Case[int, Map[T, Case[Equal[T, int], str], Default[bytes]]], "
            "Default[float]]",
            "str | bytes",
            id="nested-uncertain-output",
        ),
        param(
            "Map[T, Case[Equal[T, int], "
            "Map[Input, Case[int, str], Default[float]]], Default[bytes]]",
            "str | float | bytes",
            id="uncertain-deferred-output",
        ),
        param(
            "Map[int, Case[Equal[Map[T, Case[int, int], Default[str]], int], bytes], "
            "Default[float]]",
            "bytes | float",
            id="nested-uncertain-predicate",
        ),
        param(
            "Map[int, Case[All[Equal[T, int], Equal[int, str]], str], Default[bytes]]",
            "bytes",
            id="all-unknown-false",
        ),
        param(
            "Map[int, Case[Any[Equal[T, int], Equal[int, int]], str], Default[bytes]]",
            "str",
            id="any-unknown-true",
        ),
        param(
            "Map[int, Case[Not[Equal[T, int]], str], Default[bytes]]",
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
        "from typeforge import (\n"
        "    All, Any, Assignable, Case, Default, Equal, Map, Not, Value,\n"
        ")\n"
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
            "type Structural[A] = "
            "Map[A, Case[list[Value], set[Value]], Default[bytes]]",
            "Structural[list[int]]",
            "set[int]",
            id="structural-alias",
        ),
        param(
            "type Wire[A] = Map[A, Case[Equal[A, int], str], Default[bytes]]",
            "Wire[T]",
            "str | bytes",
            id="generic-alias",
        ),
        param(
            "type Wire[A] = Map[A, Case[int, str]]",
            "Wire[bytes]",
            "Never",
            id="alias-omitted",
        ),
        param(
            "type Wire[A] = Map[A, Case[int, str], Default[Never]]",
            "Wire[bytes]",
            "Never",
            id="alias-explicit-never",
        ),
        param(
            "type Inner[A] = Map[A, Case[int, str], Default[bytes]]\n"
            "type Outer[A] = Map[A, Case[str, float], Default[complex]]",
            "Outer[Inner[int]]",
            "float",
            id="alias-in-argument",
        ),
        param(
            "type Wire[A] = Map[A, Case[int, str], Default[bytes]]",
            "list[Wire[int]]",
            "list[str]",
            id="alias-under-application",
        ),
        param(
            "type Wire[A] = Map[A, Case[int, str], Default[bytes]]",
            "Wire[int] | None",
            "str | None",
            id="alias-under-union",
        ),
        param(
            "type Wire[A] = "
            "Map[A, Case[int, tuple[str, bytes]], Default[tuple[float]]]",
            "tuple[*Wire[int]]",
            "tuple[*tuple[str, bytes]]",
            id="alias-under-starred",
        ),
        param(
            "type Wire[A] = Map[A, Case[int, str], Default[bytes]]",
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
        "from typeforge import Case, Default, Equal, Map, Value\n"
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
            'Field[Map[Key, Case[Literal["original"], Literal["renamed"]], '
            "Default[Key]], Value]",
            "renamed: int",
            id="literal-field-name-case",
        ),
        param(
            'Field[Map[Key, Case[Equal[Key, Literal["original"]], '
            'Literal["renamed"]], Default[Key]], Value]',
            "renamed: int",
            id="literal-field-name-predicate",
        ),
        param(
            "Field[Key, Map[Value, Case[str, str]]]",
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
        "from typeforge import (\n"
        "    Case, Default, Equal, Field, Key, Map, MapFields, Value,\n"
        ")\n"
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
