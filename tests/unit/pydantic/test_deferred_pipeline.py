"""Deferred Input contracts through the public Schema annotation."""

from enum import IntEnum
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

import pytest

from pydantic import (
    AfterValidator,
    BaseModel,
    PlainSerializer,
    PydanticSchemaGenerationError,
    TypeAdapter,
    ValidationError,
)
from typeforge import Field, Key, Map, MapFields, Value
from typeforge._markers import All, Assignable, Equal, Not
from typeforge._markers import Any as AnyCondition
from typeforge._markers import Map as CanonicalMap
from typeforge.pydantic import Input, Schema


def test_deferred_selection_uses_raw_type_and_only_selected_output() -> None:
    adapter = TypeAdapter(Schema[Map[Input, str:int, int:float]])
    assert adapter.validate_python("3") == 3
    assert type(adapter.validate_python(3)) is float
    assert adapter.validate_json('"3"') == 3
    with pytest.raises(ValidationError) as failure:
        adapter.validate_python(True)

    assert failure.value.errors()[0]["type"] == "typeforge_map_no_match"
    assert failure.value.errors()[0]["input"] is True


def test_selected_failure_never_runs_later_outputs_and_has_authored_location() -> None:
    calls: list[str] = []

    def first(value: int) -> int:
        calls.append("first")
        return value

    def later(value: str) -> str:
        calls.append("later")
        return value

    type Selected = Map[
        Input,
        str : Annotated[int, AfterValidator(first)],
        str : Annotated[str, AfterValidator(later)],
        ... : Annotated[str, AfterValidator(later)],
    ]

    class Payload(BaseModel):
        values: list[Schema[Selected]]

    assert Payload(values=["3"]).values == [3]
    assert calls == ["first"]
    with pytest.raises(ValidationError) as failure:
        Payload(values=["bad"])

    error = failure.value.errors()[0]
    assert error["type"] == "int_parsing"
    assert error["loc"] == ("values", 0)
    assert error["input"] == "bad"
    assert calls == ["first"]


def test_reached_predicate_failure_is_not_a_mismatch() -> None:
    type Selected = Map[
        Input,
        All[Equal[Input, int], Equal[Key, Key]] : bytes,
        ...:str,
    ]
    adapter = TypeAdapter(Schema[Selected])
    assert adapter.validate_python("text") == "text"
    with pytest.raises(ValidationError) as failure:
        adapter.validate_python(3)

    assert failure.value.errors()[0]["type"] == "typeforge_unbound_key"
    assert failure.value.errors()[0]["input"] == 3


def test_predicate_order_and_nested_short_circuiting() -> None:
    adapter = TypeAdapter(
        Schema[
            Map[
                Input,
                Assignable[Input, int] : int,
                AnyCondition[Not[Equal[Input, int]], Equal[Key, Key]] : str,
                Equal[Key, Key] : bytes,
            ]
        ]
    )
    assert adapter.validate_python(True) == 1
    assert adapter.validate_python("text") == "text"


def test_union_tests_short_circuit_shared_predicates() -> None:
    adapter = TypeAdapter(
        Schema[
            Map[
                Input,
                int | Equal[Key, Key] : int,
                ...:str,
            ]
        ]
    )
    assert adapter.validate_python(3) == 3
    with pytest.raises(ValidationError, match="typeforge_unbound_key"):
        adapter.validate_python("text")


def test_structural_capture_remains_available_to_deferred_selection_and_output() -> (
    None
):
    type Selected = Map[
        list[int],
        list[Value] : Map[Input, Value:str, ...:Value],
    ]
    adapter = TypeAdapter(Schema[Selected])
    assert adapter.validate_python("3") == 3
    with pytest.raises(ValidationError, match="string_type"):
        adapter.validate_python(3)


class Code(IntEnum):
    ONE = 1


@pytest.mark.parametrize("raw", [True, 1.0, Code.ONE])
def test_literal_matching_distinguishes_equal_values_with_different_types(
    raw: object,
) -> None:
    adapter = TypeAdapter(Schema[Map[Input, Literal[1] : int]])
    assert adapter.validate_python(1) == 1
    with pytest.raises(ValidationError, match="typeforge_map_no_match"):
        adapter.validate_python(raw)


def test_enum_literals_and_input_catch_all() -> None:
    adapter = TypeAdapter(
        Schema[
            Map[
                Input,
                Literal[Code.ONE] : int,
                Input:str,
            ]
        ]
    )
    assert adapter.validate_python(Code.ONE) == 1
    assert adapter.validate_python("other") == "other"
    with pytest.raises(ValidationError, match="string_type"):
        adapter.validate_python(1)


def test_union_annotated_and_ordinary_alias_tests() -> None:
    def forbidden(value: object) -> object:
        raise AssertionError("matching must not run annotation validators")

    type Raw = Annotated[int | str, AfterValidator(forbidden)]
    adapter = TypeAdapter(Schema[Map[Input, Raw:int]])
    assert adapter.validate_python("3") == 3
    assert adapter.validate_python(3) == 3
    with pytest.raises(ValidationError, match="typeforge_map_no_match"):
        adapter.validate_python(True)


@pytest.mark.parametrize(
    "pattern",
    [
        list[int],
        list[Value],
        int | list[int],
        Annotated[list[int], "metadata"],
    ],
)
def test_parameterized_runtime_patterns_fail_during_construction(
    pattern: object,
) -> None:
    with pytest.raises(
        PydanticSchemaGenerationError, match="unsupported_runtime_pattern"
    ):
        TypeAdapter(Schema[Map[Input, pattern:str]])


def test_aliases_do_not_hide_unsupported_patterns() -> None:
    type Hidden = int | list[str]
    with pytest.raises(
        PydanticSchemaGenerationError, match="unsupported_runtime_pattern"
    ):
        TypeAdapter(Schema[Map[Input, Hidden:str]])


def test_generic_alias_tests_use_existing_binding_inside_unions() -> None:
    type Raw[T] = Annotated[T, "metadata"]
    adapter = TypeAdapter(Schema[Map[Input, Raw[int] | str : int]])
    assert adapter.validate_python(3) == 3
    assert adapter.validate_python("3") == 3
    with pytest.raises(
        PydanticSchemaGenerationError, match="unsupported_runtime_pattern"
    ):
        TypeAdapter(Schema[Map[Input, Raw[list[int]] | str : int]])


def test_empty_deferred_map_is_an_uninhabited_validator() -> None:
    adapter = TypeAdapter(Schema[CanonicalMap[Input]])
    with pytest.raises(ValidationError, match="typeforge_map_no_match"):
        adapter.validate_python("anything")

    assert adapter.json_schema() == {}


def test_unbound_capture_is_invalid_without_inspecting_input_values() -> None:
    with pytest.raises(PydanticSchemaGenerationError, match="unbound_value"):
        TypeAdapter(Schema[Map[Input, Value:str]])


def test_nested_maps_observe_same_raw_value_and_container_items_observe_each_item() -> (
    None
):
    type Inner = Map[Input, str:int, ...:float]
    type Outer = Map[Input, str:Inner, ...:float]
    adapter = TypeAdapter(Schema[list[Outer]])
    assert adapter.validate_python(["3", 3]) == [3, 3.0]
    assert adapter.validate_json('["3", 3]') == [3, 3.0]
    with pytest.raises(ValidationError) as failure:
        adapter.validate_python(["bad"])

    assert failure.value.errors()[0]["loc"] == (0,)


def test_input_inside_annotated_output_and_record_field_preserves_context() -> None:
    class Source(TypedDict):
        count: int
        label: str

    type Transformed = MapFields[
        Source,
        Field[
            Key,
            Annotated[
                Map[
                    Input,
                    Equal[Input, Value] : Value,
                    ...:bytes,
                ],
                AfterValidator(lambda value: value),
            ],
        ],
    ]
    adapter = TypeAdapter(Schema[Transformed])
    assert adapter.validate_python({"count": 3, "label": "ok"}) == {
        "count": 3,
        "label": "ok",
    }
    assert adapter.validate_python({"count": "3", "label": b"ok"}) == {
        "count": b"3",
        "label": b"ok",
    }


def test_generic_static_fallback_is_independent_of_input() -> None:
    class Payload[T](BaseModel):
        value: Schema[Map[Input, str : Map[T, int:int, ...:bytes]]]

    assert Payload(value="3").value == 3
    assert Payload[Any](value="3").value == 3
    assert Payload[int](value="3").value == 3
    assert Payload[bytes](value="3").value == b"3"
    Payload.model_rebuild(force=True)
    assert Payload(value="3").value == 3


def test_serialization_uses_output_types_and_never_redispatches_coerced_input() -> None:
    adapter = TypeAdapter(
        Schema[
            Map[
                Input,
                str : Annotated[
                    int,
                    PlainSerializer(lambda value: f"int:{value}", return_type=str),
                ],
                int : Annotated[
                    float,
                    PlainSerializer(lambda value: f"float:{value}", return_type=str),
                ],
            ]
        ]
    )
    integer = adapter.validate_python("3")
    floating = adapter.validate_python(3)
    assert adapter.dump_python(integer) == "int:3"
    assert adapter.dump_json(integer) == b'"int:3"'
    assert adapter.dump_python(floating) == "float:3.0"
    assert adapter.dump_json(floating) == b'"float:3.0"'
    assert adapter.json_schema(mode="validation") == {}
    assert adapter.json_schema(mode="serialization") == {}


def test_uuid_output_serialization_and_default() -> None:
    adapter = TypeAdapter(Schema[Map[Input, str:UUID, ...:int]])
    text = "550e8400-e29b-41d4-a716-446655440000"
    output = adapter.validate_json(f'"{text}"')
    assert output == UUID(text)
    assert adapter.dump_json(output) == f'"{text}"'.encode()
    assert adapter.validate_python(3) == 3


def test_model_outputs_preserve_references_middleware_and_error_details() -> None:
    from pydantic import Field as PydanticField

    class Child(BaseModel):
        count: int = PydanticField(gt=0)

    class Payload(BaseModel):
        first: Schema[Map[Input, dict:Child, ...:int]]
        second: Schema[Map[Input, dict:Child, ...:int]]

    payload = Payload(first={"count": "3"}, second=4)
    assert payload.model_dump() == {"first": {"count": 3}, "second": 4}
    assert payload.model_dump_json() == '{"first":{"count":3},"second":4}'
    with pytest.raises(ValidationError) as failure:
        Payload(first={"count": 0}, second=4)

    error = failure.value.errors()[0]
    assert error["type"] == "greater_than"
    assert error["ctx"] == {"gt": 0}
    assert error["loc"] == ("first", "count")
    assert error["input"] == 0
    before = Payload.model_json_schema()
    Payload.model_rebuild(force=True)
    assert Payload.model_json_schema() == before


def test_unexpected_output_failure_propagates_identity() -> None:
    expected = RuntimeError("validator failed")

    def fail(value: int) -> int:
        raise expected

    adapter = TypeAdapter(
        Schema[Map[Input, str : Annotated[int, AfterValidator(fail)]]]
    )
    with pytest.raises(RuntimeError) as failure:
        adapter.validate_python("3")

    assert failure.value is expected
