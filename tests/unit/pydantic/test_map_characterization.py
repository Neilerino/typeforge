from typing import Annotated, Literal, Never
from typing import Any as TypingAny

import pytest

from pydantic import (
    AfterValidator,
    PydanticSchemaGenerationError,
    TypeAdapter,
    ValidationError,
)
from typeforge import Map, Value
from typeforge.pydantic import Schema


@pytest.mark.parametrize(
    ("expression", "raw", "expected"),
    [
        pytest.param(
            Map[TypingAny, int:str, ...:bytes],
            "3",
            b"3",
            id="any-exact-mismatch-default",
        ),
        pytest.param(
            Map[TypingAny, list[Value] : set[Value], ...:TypingAny],
            ["3"],
            ["3"],
            id="any-has-no-list-structure",
        ),
        pytest.param(
            Map[list[TypingAny], list[Value] : set[Value]],
            ["3", 4],
            {"3", 4},
            id="list-any-captures-any",
        ),
        pytest.param(
            Map[TypingAny, TypingAny:str],
            "3",
            "3",
            id="explicit-any-case",
        ),
        pytest.param(
            Map[TypingAny, int:bytes, TypingAny:str],
            "3",
            "3",
            id="mismatch-continues-to-later-case",
        ),
    ],
)
def test_schema_any_cases_preserve_exact_and_structural_roles(
    expression: object, raw: object, expected: object
) -> None:
    adapter = TypeAdapter[object](Schema[expression])

    actual = adapter.validate_python(raw)

    assert actual == expected
    assert type(actual) is type(expected)


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(Map[TypingAny, int:str], id="exact-no-match"),
        pytest.param(
            Map[TypingAny, list[Value] : set[Value]],
            id="structural-no-match",
        ),
        pytest.param(
            Map[TypingAny, int:str, ...:Never],
            id="explicit-never-default",
        ),
        pytest.param(Map[TypingAny, TypingAny:Never], id="selected-never"),
    ],
)
def test_schema_rejects_empty_output_at_construction(expression: object) -> None:
    # Retain rejection, without freezing the old emitter's incidental Never error.
    with pytest.raises(PydanticSchemaGenerationError):
        TypeAdapter[object](Schema[expression])


def test_structural_map_reconciles_repeated_captures() -> None:
    type Matched = Map[tuple[int, int], tuple[Value, Value] : list[Value], ...:bytes]
    type Mismatched = Map[tuple[int, str], tuple[Value, Value] : list[Value], ...:bytes]

    assert TypeAdapter[object](Schema[Matched]).validate_python(["3"]) == [3]
    assert TypeAdapter[object](Schema[Mismatched]).validate_python("3") == b"3"


def test_failed_structural_case_does_not_leak_capture_to_next_case() -> None:
    type Selected = Map[
        tuple[int, str],
        tuple[Value, bytes] : bytes,
        tuple[int, Value] : list[Value],
    ]
    adapter = TypeAdapter[object](Schema[Selected])

    assert adapter.validate_python(["text"]) == ["text"]
    with pytest.raises(ValidationError):
        adapter.validate_python([3])


def test_nested_capture_templates_preserve_union_and_literal_types() -> None:
    type Selected = Map[
        list[int],
        list[Value] : tuple[Value | None, Literal["accepted"]],
    ]
    adapter = TypeAdapter[object](Schema[Selected])

    assert adapter.validate_python(["3", "accepted"]) == (3, "accepted")
    assert adapter.validate_python([None, "accepted"]) == (None, "accepted")
    with pytest.raises(ValidationError):
        adapter.validate_python([3, "rejected"])


def test_variadic_alias_binds_each_argument_before_structural_capture() -> None:
    type Packed[*Items] = Map[
        tuple[*Items], tuple[Value, Value] : list[Value], ...:bytes
    ]

    assert TypeAdapter[object](Schema[Packed[int, int]]).validate_python(["3"]) == [3]
    assert TypeAdapter[object](Schema[Packed[int, str]]).validate_python("3") == b"3"


def test_schema_nested_beneath_container_retains_leaf_constraints() -> None:
    from pydantic import Field

    type Positive = Annotated[int, Field(gt=0)]
    adapter = TypeAdapter[object](list[Schema[Map[int, int:Positive]]])

    assert adapter.validate_python(["3"]) == [3]
    with pytest.raises(ValidationError) as captured:
        adapter.validate_python([0])

    assert captured.value.errors()[0]["loc"] == (0,)


def test_schema_preserves_metadata_inside_and_outside_the_annotation() -> None:
    calls: list[str] = []

    def inner(value: int) -> int:
        calls.append("inner")
        return value + 1

    def outer(value: int) -> int:
        calls.append("outer")
        return value * 2

    type Selected = Annotated[Map[int, int:int], AfterValidator(inner)]
    adapter = TypeAdapter[object](Annotated[Schema[Selected], AfterValidator(outer)])

    assert adapter.validate_python("3") == 8
    assert calls == ["inner", "outer"]
