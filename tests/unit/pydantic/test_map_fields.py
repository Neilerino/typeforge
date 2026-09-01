from typing import Annotated, Literal, NotRequired, ReadOnly, TypedDict

import pytest

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic import Field as PydanticField
from typeforge import (
    Case,
    Default,
    Drop,
    Equal,
    Field,
    Key,
    Map,
    MapFields,
    OptionalField,
    ReadonlyField,
    Value,
)
from typeforge.pydantic import Schema


class User(TypedDict):
    name: str
    attempts: int
    password: str


type Public[T] = MapFields[
    T,
    Map[
        Key,
        Case[Equal[Key, Literal["password"]], Drop],
        Default[
            Field[
                Key,
                Map[Value, Case[int, str], Default[Value]],
            ]
        ],
    ],
]


def test_map_fields_validates_transforms_and_drops_fields() -> None:
    adapter = TypeAdapter(Schema[Public[User]])

    value = adapter.validate_python(
        {"name": "Ada", "attempts": "2", "password": "secret"}
    )

    assert value == {"name": "Ada", "attempts": "2"}
    assert type(value) is dict


def test_map_fields_preserves_nested_error_location() -> None:
    class Request(BaseModel):
        user: Schema[Public[User]]

    with pytest.raises(ValidationError) as captured:
        Request(user={"name": "Ada", "attempts": [], "password": "secret"})

    assert captured.value.errors()[0]["loc"] == ("user", "attempts")


def test_map_fields_can_rename_and_make_fields_optional() -> None:
    type Renamed[T] = MapFields[
        T,
        Map[
            Key,
            Case[
                Equal[Key, Literal["name"]],
                OptionalField[Literal["display_name"], Value],
            ],
            Default[Drop],
        ],
    ]
    adapter = TypeAdapter(Schema[Renamed[User]])

    assert adapter.validate_python({}) == {}
    assert adapter.validate_python({"display_name": "Ada"}) == {"display_name": "Ada"}


def test_map_fields_supports_inherited_non_total_and_readonly_fields() -> None:
    class Base(TypedDict, total=False):
        note: str

    class Payload(Base):
        identifier: int
        token: ReadOnly[NotRequired[bytes]]

    type Copy[T] = MapFields[T, ReadonlyField[Key, Value]]
    adapter = TypeAdapter(Schema[Copy[Payload]])

    assert adapter.validate_python(
        {"identifier": "1", "note": "ok", "token": "abc"}
    ) == {"identifier": 1, "note": "ok", "token": b"abc"}
    assert adapter.json_schema()["properties"]["token"]["readOnly"] is True


def test_map_fields_preserves_constrained_leaf_metadata() -> None:
    class Payload(TypedDict):
        count: Annotated[int, PydanticField(gt=0)]

    type Copy[T] = MapFields[T, Field[Key, Value]]
    adapter = TypeAdapter(Schema[Copy[Payload]])

    assert adapter.validate_python({"count": "2"}) == {"count": 2}
    with pytest.raises(ValidationError):
        adapter.validate_python({"count": 0})


def test_map_fields_rejects_non_typed_dict_records() -> None:
    type Invalid = Schema[MapFields[User, Field[Literal["same"], Value]]]

    with pytest.raises(Exception, match="duplicate_field"):
        TypeAdapter(Invalid)

    class Model(BaseModel):
        value: int

    with pytest.raises(Exception, match="supports TypedDict records only"):
        TypeAdapter(Schema[MapFields[Model, Field[Key, Value]]])
