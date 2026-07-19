from typing import Annotated

import pytest

from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from typeforge import All, Any, Assignable, Case, Default, Equal, Map, Not
from typeforge.pydantic import Schema


def test_schema_is_not_a_value_wrapper() -> None:
    adapter = TypeAdapter(Schema[int])

    value = adapter.validate_python("3")

    assert value == 3
    assert type(value) is int


def test_schema_works_as_base_model_field() -> None:
    class Model(BaseModel):
        value: Schema[Map[int, Case[Equal[int, int], int], Default[bytes]]]

    model = Model(value="3")

    assert model.value == 3
    assert type(model.value) is int


def test_schema_preserves_ordinary_pydantic_metadata() -> None:
    type Positive = Annotated[int, Field(gt=0)]
    adapter = TypeAdapter(Schema[Positive])

    assert adapter.validate_python("2") == 2
    with pytest.raises(ValidationError):
        adapter.validate_python(0)


def test_schema_time_conditions_compose() -> None:
    type Selected = Schema[
        Map[
            int,
            Case[
                All[
                    Equal[int, int],
                    Assignable[int, object],
                    Not[Any[Equal[int, str], Equal[int, bytes]]],
                ],
                list[int],
            ],
            Default[dict[str, int]],
        ]
    ]
    adapter = TypeAdapter(Selected)

    assert adapter.validate_python(["1", 2]) == [1, 2]
    with pytest.raises(ValidationError):
        adapter.validate_python({"value": 1})


def test_schema_time_map_selects_case_and_default() -> None:
    type Selected[T] = Map[
        T,
        Case[int, float],
        Case[bytes, str],
        Default[T],
    ]

    bytes_adapter = TypeAdapter(Schema[Selected[bytes]])
    list_adapter = TypeAdapter(Schema[Selected[list[int]]])

    assert bytes_adapter.validate_python(b"hello") == "hello"
    assert list_adapter.validate_python(["1", 2]) == [1, 2]


def test_schema_time_map_distributes_over_union() -> None:
    adapter = TypeAdapter(
        Schema[
            Map[
                int | bytes,
                Case[int, float],
                Case[bytes, str],
            ]
        ]
    )

    assert adapter.validate_python(1.5) == 1.5
    assert adapter.validate_python("value") == "value"


def test_schema_time_map_without_a_match_resolves_to_never() -> None:
    with pytest.raises(Exception, match="Never"):
        TypeAdapter(Schema[Map[bytes, Case[int, str]]])


def test_schema_time_resolution_emits_no_python_validator() -> None:
    adapter = TypeAdapter(
        Schema[Map[int, Case[Equal[int, int], list[int]], Default[bytes]]]
    )

    def contains_function_schema(value: object) -> bool:
        if isinstance(value, dict):
            if str(value.get("type", "")).startswith("function-"):
                return True
            return any(contains_function_schema(item) for item in value.values())
        if isinstance(value, list | tuple):
            return any(contains_function_schema(item) for item in value)
        return False

    assert not contains_function_schema(adapter.core_schema)
