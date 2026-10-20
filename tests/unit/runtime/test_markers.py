import ast
from dataclasses import FrozenInstanceError
from textwrap import dedent
from typing import Annotated, Literal, get_args, get_origin

import pytest

from typeforge import Collect, Doc, Drop, Each, Field, Map
from typeforge._markers import All, Any, Assignable, Case, Default, Equal, Not


def test_variadic_markers_preserve_arguments() -> None:
    assert get_args(Each[int]) == (int,)
    assert get_args(Collect[int]) == (int,)


def test_condition_markers_preserve_arguments() -> None:
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
    mapping = Map[int, int:str, ...:bytes]
    assert get_args(mapping) == (int, Case[int, str], Default[bytes])
    conditional = Map[
        int,
        Assignable[int, object] : str,
        ...:bytes,
    ]
    assert get_args(conditional) == (
        int,
        Case[Assignable[int, object], str],
        Default[bytes],
    )


def test_field_constructor_preserves_explicit_data() -> None:
    assert get_args(Field(name="name", type=int)) == (Literal["name"], int, True, False)
    assert get_args(Field(name="name", type=int, required=False)) == (
        Literal["name"],
        int,
        False,
        False,
    )
    assert get_args(Field(name="name", type=int, readonly=True)) == (
        Literal["name"],
        int,
        True,
        True,
    )
    assert repr(Drop) == "Drop"


def test_every_marker_carries_markdown_documentation() -> None:
    markers = (
        Each,
        Collect,
        Assignable,
        Equal,
        All,
        Any,
        Not,
        Map,
        Drop,
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


def test_field_constructor_has_documented_keyword_authoring() -> None:
    documentation = Field.__doc__
    assert documentation is not None
    assert len(documentation) >= 180
    example = documentation.split("```python\n", 1)[1].split("```", 1)[0]
    ast.parse(dedent(example))


def test_doc_is_public_inert_metadata() -> None:
    documentation = Doc("A reusable type.")

    assert documentation.documentation == "A reusable type."
    attribute = "documentation"
    with pytest.raises(FrozenInstanceError):
        setattr(documentation, attribute, "Changed.")
