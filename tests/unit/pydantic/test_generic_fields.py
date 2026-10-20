from typing import Annotated, Generic, TypeVar

import pytest

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
)
from typeforge import Is, Map, Value
from typeforge.pydantic import Schema


def test_generic_alias_fields_rebuild_and_keep_specializations_independent() -> None:
    type Selected[T] = Map[T, int:str, ...:bytes]

    class Payload[T](BaseModel):
        value: Schema[Selected[T]]

    class Pair(BaseModel):
        text: Payload[int]
        binary: Payload[bytes]

    value = Pair.model_validate({"text": {"value": "3"}, "binary": {"value": "4"}})

    assert value.text.value == "3"
    assert value.binary.value == b"4"
    assert value.model_dump(mode="json") == {
        "text": {"value": "3"},
        "binary": {"value": "4"},
    }
    before = Pair.model_json_schema()
    assert (
        before["properties"]["text"]["$ref"] != before["properties"]["binary"]["$ref"]
    )
    assert Payload[int].model_json_schema() != Payload[bytes].model_json_schema()
    Payload[bytes].model_rebuild(force=True)
    Payload[int].model_rebuild(force=True)
    Pair.model_rebuild(force=True)
    assert Pair.model_json_schema() == before
    assert Payload[int].model_validate_json('{"value":"3"}').value == "3"
    assert Payload[bytes].model_validate_json('{"value":"3"}').value == b"3"


def test_partial_generic_inheritance_substitutes_nested_structural_fields() -> None:
    class Parent[T, U](BaseModel):
        value: Schema[Map[list[T], list[Value] : set[Value], ...:bytes]]
        other: list[Schema[U]]

    class Child[U](Parent[int, U]):
        pass

    result = Child[str].model_validate({"value": ["3"], "other": ["x"]})

    assert result.value == {3}
    assert result.other == ["x"]
    with pytest.raises(ValidationError):
        Child[str].model_validate({"value": ["3"], "other": [1]})


def test_traditional_generic_field_substitutes_typevars() -> None:
    T = TypeVar("T")

    # Keep the traditional spelling as an integration compatibility contract.
    class Payload(BaseModel, Generic[T]):
        value: Schema[Map[T, int:str, ...:bytes]]

    assert Payload[int].model_validate({"value": "3"}).value == "3"
    assert Payload[bytes].model_validate({"value": "3"}).value == b"3"


def test_ordinary_schema_typevar_preserves_pydantic_fallbacks() -> None:
    class Plain[T, B: int, C: (int, str), D = str](BaseModel):
        unbound: T
        bound: B
        constrained: C
        defaulted: D

    class Wrapped[T, B: int, C: (int, str), D = str](BaseModel):
        unbound: Schema[T]
        bound: Schema[B]
        constrained: Schema[C]
        defaulted: Schema[D]

    raw = {"unbound": {"x": 1}, "bound": "3", "constrained": "text", "defaulted": "x"}

    assert (
        Wrapped.model_validate(raw).model_dump()
        == Plain.model_validate(raw).model_dump()
    )
    assert (
        Wrapped.model_validate(raw).model_dump_json()
        == Plain.model_validate(raw).model_dump_json()
    )
    with pytest.raises(ValidationError):
        Wrapped.model_validate({**raw, "bound": "invalid"})


def test_ordinary_model_bound_typevar_preserves_pydantic_serialization() -> None:
    class Detail(BaseModel):
        label: str

    class ExtraDetail(Detail):
        extra: int

    class Plain[T: Detail](BaseModel):
        value: T

    class Wrapped[T: Detail](BaseModel):
        value: Schema[T]

    detail = ExtraDetail(label="x", extra=3)

    assert Wrapped(value=detail).model_dump() == Plain(value=detail).model_dump()
    assert (
        Wrapped[Detail](value=detail).model_dump()
        == Plain[Detail](value=detail).model_dump()
    )
    assert Wrapped(value=detail).model_dump() == {"value": {"label": "x", "extra": 3}}
    assert Wrapped[Detail](value=detail).model_dump() == {"value": {"label": "x"}}


def test_generic_field_preserves_model_configuration_and_field_middleware() -> None:
    class Payload[T](BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: Annotated[
            Schema[Map[T, int:int, ...:T]],
            Field(gt=0, alias="amount"),
        ]

        @field_validator("value")
        @classmethod
        def double(cls, value: int) -> int:
            return value * 2

        @field_serializer("value")
        def describe(self, value: int) -> str:
            return f"value:{value}"

    result = Payload[int].model_validate({"amount": "3"})

    assert result.value == 6
    assert result.model_dump(by_alias=True) == {"amount": "value:6"}
    with pytest.raises(ValidationError) as captured:
        Payload[int].model_validate({"amount": 0})

    assert captured.value.errors()[0]["loc"] == ("amount",)
    with pytest.raises(ValidationError):
        Payload[int].model_validate({"amount": 1, "extra": True})


def test_generic_no_default_map_specializes_and_rejects_unmatched_any() -> None:
    class Payload[T](BaseModel):
        value: Schema[Map[T, Is[int] : str, Is[bytes] : int]]

    assert Payload[int].model_validate({"value": "3"}).value == "3"
    assert Payload[bytes].model_validate({"value": "3"}).value == 3
    with pytest.raises(ValidationError) as captured:
        Payload.model_validate({"value": "3"})

    issue = captured.value.errors()[0]
    assert issue["type"] == "typeforge_map_no_match"
    assert issue["loc"] == ("value",)
    assert "Any" in issue["msg"]
    Payload[int].model_rebuild(force=True)
    assert Payload[int].model_validate({"value": "3"}).value == "3"


def test_generic_map_delegates_selected_model_output_to_pydantic() -> None:
    class Item[T](BaseModel):
        value: T

    class Payload[T](BaseModel):
        value: Schema[Map[T, int : Item[int], ... : Item[T]]]

    integer = Payload[int].model_validate({"value": {"value": "3"}})
    text = Payload[str].model_validate({"value": {"value": "x"}})

    assert isinstance(integer.value, Item[int])
    assert integer.value.value == 3
    assert isinstance(text.value, Item[str])
    assert text.value.value == "x"
    assert integer.model_dump() == {"value": {"value": 3}}
