import ast
from dataclasses import FrozenInstanceError
from typing import Annotated, get_args, get_origin

import pytest

from typeforge import (
    All,
    Any,
    Assignable,
    Case,
    Collect,
    Default,
    Doc,
    Drop,
    Each,
    Equal,
    Field,
    If,
    Key,
    Map,
    MapFields,
    Not,
    OptionalField,
    ReadonlyField,
    Value,
)


def test_variadic_markers_preserve_arguments() -> None:
    assert get_args(Each[int]) == (int,)
    assert get_args(Collect[int]) == (int,)


def test_condition_markers_preserve_arguments() -> None:
    assert get_args(If[Assignable[int, object], str, bytes]) == (
        Assignable[int, object],
        str,
        bytes,
    )
    assert get_args(Equal[int, str]) == (int, str)
    assert get_args(All[Equal[int, int], Assignable[int, object]]) == (
        Equal[int, int],
        Assignable[int, object],
    )
    assert get_args(Any[Equal[int, str], Equal[int, int]]) == (
        Equal[int, str],
        Equal[int, int],
    )
    assert get_args(Not[Equal[int, str]]) == (Equal[int, str],)


def test_map_markers_preserve_arguments() -> None:
    mapping = Map[int, Case[int, str], Default[bytes]]
    assert get_args(mapping) == (int, Case[int, str], Default[bytes])


def test_field_markers_preserve_arguments() -> None:
    assert get_args(MapFields[dict[str, int], Field[Key, Value]]) == (
        dict[str, int],
        Field[Key, Value],
    )
    assert get_args(OptionalField[Key, Value]) == (Key, Value)
    assert get_args(ReadonlyField[Key, Value]) == (Key, Value)
    assert repr(Drop) == "Drop"


def test_every_marker_carries_markdown_documentation() -> None:
    markers = (
        Each,
        Collect,
        If,
        Assignable,
        Equal,
        All,
        Any,
        Not,
        Case,
        Default,
        Map,
        MapFields,
        Field,
        OptionalField,
        ReadonlyField,
        Drop,
        Key,
        Value,
    )

    for marker in markers:
        marker_value = marker.__value__
        assert get_origin(marker_value) is Annotated
        documentation = get_args(marker_value)[-1]
        assert isinstance(documentation, Doc)
        assert len(documentation.documentation) >= 180
        example_start = documentation.documentation.index("```python\n") + len(
            "```python\n"
        )
        example_end = documentation.documentation.index("\n```", example_start)
        ast.parse(documentation.documentation[example_start:example_end])


def test_doc_is_public_inert_metadata() -> None:
    documentation = Doc("A reusable type.")

    assert documentation.documentation == "A reusable type."
    attribute = "documentation"
    with pytest.raises(FrozenInstanceError):
        setattr(documentation, attribute, "Changed.")
