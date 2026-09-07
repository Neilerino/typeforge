from typing import Annotated, Any, Literal, NotRequired, ReadOnly, TypedDict

import pytest

from pydantic import (
    AfterValidator,
    BaseModel,
    PydanticSchemaGenerationError,
    TypeAdapter,
    ValidationError,
)
from pydantic import Field as PydanticField
from typeforge import (
    Case,
    Default,
    Doc,
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


def test_record_transforms_validate_rename_drop_and_preserve_leaf_constraints() -> None:
    class User(TypedDict):
        name: str
        count: Annotated[int, PydanticField(gt=0)]
        password: str

    type Public[T] = MapFields[
        T,
        Map[
            Key,
            Case[Equal[Key, Literal["password"]], Drop],
            Case[
                Equal[Key, Literal["name"]],
                OptionalField[Literal["display_name"], Value],
            ],
            Default[Field[Key, Value]],
        ],
    ]

    class Request(BaseModel):
        user: Schema[Public[User]]

    result = Request.model_validate({"user": {"count": "2", "password": "secret"}})
    assert result.model_dump() == {"user": {"count": 2}}
    with pytest.raises(ValidationError) as captured:
        Request.model_validate({"user": {"count": 0}})

    assert captured.value.errors()[0]["loc"] == ("user", "count")


def test_record_metadata_and_references_survive_repeated_fields_and_rebuild() -> None:
    class User(TypedDict):
        name: str

    type Public[T] = Annotated[MapFields[T, Field[Key, Value]], Doc("Public record")]

    class Pair(BaseModel):
        first: Schema[Public[User]]
        second: Schema[Public[User]]

    schema = Pair.model_json_schema()
    assert len(schema["$defs"]) == 1
    definition = next(iter(schema["$defs"].values()))
    assert definition["description"] == "Public record"
    assert definition["required"] == ["name"]
    assert (
        schema["properties"]["first"]["$ref"] == schema["properties"]["second"]["$ref"]
    )
    Pair.model_rebuild(force=True)
    assert Pair.model_json_schema() == schema


def test_generic_record_fields_allow_origins_and_independent_specializations() -> None:
    class Left(TypedDict):
        count: int

    class Right(TypedDict):
        label: str

    class Payload[T](BaseModel):
        value: Schema[MapFields[T, Field[Key, Value]]]

    assert Payload[Left].model_validate({"value": {"count": "3"}}).model_dump() == {
        "value": {"count": 3}
    }
    assert Payload[Right].model_validate({"value": {"label": "x"}}).model_dump() == {
        "value": {"label": "x"}
    }
    with pytest.raises(ValidationError) as captured:
        Payload.model_validate({"value": {"invented": 3}})

    assert captured.value.errors()[0]["type"] == "typeforge_unsupported_record"
    assert captured.value.errors()[0]["loc"] == ("value",)


def test_generic_typed_dict_fields_bind_before_structural_transforms() -> None:
    class Items[T](TypedDict):
        values: list[T]

    type Converted[T] = MapFields[
        Items[T], Field[Key, Map[Value, Case[list[Value], set[Value]]]]
    ]

    class Payload[T](BaseModel):
        value: Schema[Converted[T]]

    assert Payload[int].model_validate({"value": {"values": ["3"]}}).model_dump() == {
        "value": {"values": {3}}
    }
    assert Payload[str].model_validate({"value": {"values": ["3"]}}).model_dump() == {
        "value": {"values": {"3"}}
    }
    assert Payload[int].model_json_schema() != Payload[str].model_json_schema()


def test_record_adaptation_preserves_inherited_qualifiers_and_nested_metadata() -> None:
    from typeforge.pydantic._records import record_shape

    class Base(TypedDict, total=False):
        note: str

    class Payload(Base):
        identifier: int
        token: Annotated[ReadOnly[NotRequired[bytes]], Doc("Token")]

    shape = record_shape(Payload).unwrap()
    assert [(field.name, field.required, field.readonly) for field in shape.fields] == [
        ("note", False, False),
        ("identifier", True, False),
        ("token", False, True),
    ]
    adapter = TypeAdapter[object](Schema[MapFields[Payload, ReadonlyField[Key, Value]]])
    assert adapter.validate_python({"note": "x", "identifier": "3", "token": "a"}) == {
        "note": "x",
        "identifier": 3,
        "token": b"a",
    }
    assert adapter.json_schema()["properties"]["token"]["readOnly"] is True
    assert adapter.json_schema()["properties"]["token"]["description"] == "Token"


def test_a_map_can_select_an_annotated_record() -> None:
    class User(TypedDict):
        name: str

    type Selected = Map[
        int,
        Case[
            int, Annotated[MapFields[User, Field[Key, Value]], Doc("Selected record")]
        ],
    ]
    adapter = TypeAdapter[object](Schema[Selected])
    assert adapter.validate_python({"name": "Ada"}) == {"name": "Ada"}
    assert adapter.json_schema()["description"] == "Selected record"


def test_record_middleware_runs_once_without_leaking_into_children() -> None:
    class User(TypedDict):
        count: int

    calls: list[str] = []

    def inner(value: dict[str, int]) -> dict[str, int]:
        calls.append("inner")
        return {"count": value["count"] + 1}

    def outer(value: dict[str, int]) -> dict[str, int]:
        calls.append("outer")
        return {"count": value["count"] * 2}

    type Selected = Annotated[MapFields[User, Field[Key, Value]], AfterValidator(inner)]
    adapter = TypeAdapter[object](Annotated[Schema[Selected], AfterValidator(outer)])
    assert adapter.validate_python({"count": "3"}) == {"count": 8}
    assert calls == ["inner", "outer"]


def test_qualified_record_names_and_transform_literals_keep_refs_independent() -> None:
    class Left:
        class User(TypedDict):
            left: int

    class Right:
        class User(TypedDict):
            right: str

    class Pair(BaseModel):
        left: Schema[MapFields[Left.User, Field[Key, Value]]]
        right: Schema[MapFields[Right.User, Field[Key, Value]]]
        renamed: Schema[
            MapFields[Left.User, Field[Literal["renamed"], Literal["fixed"]]]
        ]

    result = Pair.model_validate(
        {
            "left": {"left": "3"},
            "right": {"right": "x"},
            "renamed": {"renamed": "fixed"},
        }
    )
    assert result.model_dump(mode="json") == {
        "left": {"left": 3},
        "right": {"right": "x"},
        "renamed": {"renamed": "fixed"},
    }
    for mode in ("validation", "serialization"):
        schema = Pair.model_json_schema(mode=mode)
        refs = [field["$ref"] for field in schema["properties"].values()]
        assert len(set(refs)) == 3
        Pair.model_rebuild(force=True)
        assert Pair.model_json_schema(mode=mode) == schema


def test_invalid_record_uses_do_not_invent_fields_or_defer_unrelated_failures() -> None:
    class Model(BaseModel):
        value: int

    for record in (Any, int, Model):
        with pytest.raises(PydanticSchemaGenerationError, match="unsupported_record"):
            TypeAdapter[object](Schema[MapFields[record, Field[Key, Value]]])

    with pytest.raises(PydanticSchemaGenerationError, match="unsupported_record"):

        class Payload[T](BaseModel):
            value: Schema[MapFields[int, Field[Key, T]]]


@pytest.mark.parametrize(
    ("transform", "code"),
    [
        (Field[Literal["same"], Value], "duplicate_field"),
        (Value, "expected_field"),
        (Field[Literal[3], Value], "expected_field_name"),
    ],
)
def test_invalid_field_transforms_fail_before_validation(
    transform: object, code: str
) -> None:
    class User(TypedDict):
        left: int
        right: str

    with pytest.raises(PydanticSchemaGenerationError, match=code):
        TypeAdapter[object](Schema[MapFields[User, transform]])


def test_partial_generic_records_and_defaults_follow_pydantic_lifecycle() -> None:
    class User(TypedDict):
        count: int

    class Parent[T, U](BaseModel):
        value: Schema[MapFields[T, Field[Key, Value]]]
        other: U

    class Child[U](Parent[User, U]):
        pass

    class Defaulted[T = User](BaseModel):
        value: Schema[MapFields[T, Field[Key, Value]]]

    class Bound[T: User](BaseModel):
        value: Schema[MapFields[T, Field[Key, Value]]]

    assert Child[str].model_validate_json(
        '{"value":{"count":"3"},"other":"x"}'
    ).model_dump() == {"value": {"count": 3}, "other": "x"}
    assert Defaulted.model_validate({"value": {"count": "3"}}).model_dump() == {
        "value": {"count": 3}
    }
    assert Bound.model_validate({"value": {"count": "3"}}).model_dump() == {
        "value": {"count": 3}
    }


def test_inherited_generic_typed_dict_arguments_bind_before_field_mapping() -> None:
    class Base[T](TypedDict):
        first: list[T]

    class Child[U](Base[int]):
        second: list[U]

    type Selected[T] = MapFields[
        T, Field[Key, Map[Value, Case[list[Value], set[Value]]]]
    ]
    result = TypeAdapter[object](Schema[Selected[Child[str]]]).validate_python(
        {"first": ["3"], "second": ["x"]}
    )
    assert result == {"first": {3}, "second": {"x"}}


def test_missing_record_field_name_can_be_resolved_by_model_rebuild() -> None:
    class User(TypedDict):
        field: Later

    class Payload(BaseModel):
        value: Schema[MapFields[User, Field[Key, Value]]]

    assert not Payload.__pydantic_complete__
    Later = int
    assert Payload.model_rebuild()
    assert Payload.model_validate({"value": {"field": "3"}}).model_dump() == {
        "value": {"field": 3}
    }


def test_resolved_record_outputs_need_no_validation_callbacks() -> None:
    class User(TypedDict):
        value: int

    adapter = TypeAdapter[object](Schema[MapFields[User, Field[Key, Value]]])
    assert adapter.validate_json('{"value":"3"}') == {"value": 3}
    assert "function-" not in repr(adapter.core_schema)


def test_copied_model_bound_typevars_keep_pydantic_serialization() -> None:
    class Detail(BaseModel):
        label: str

    class ExtraDetail(Detail):
        extra: int

    class Item[T](TypedDict):
        detail: T

    class Payload[T: Detail](BaseModel):
        value: Schema[MapFields[Item[T], Field[Key, Value]]]

    raw = {"value": {"detail": ExtraDetail(label="x", extra=3)}}
    assert Payload.model_validate(raw).model_dump() == {
        "value": {"detail": {"label": "x", "extra": 3}}
    }
    assert Payload[Detail].model_validate(raw).model_dump() == {
        "value": {"detail": {"label": "x"}}
    }


def test_unexpected_record_leaf_hook_failure_keeps_exception_identity() -> None:
    from pydantic_core import CoreSchema

    from pydantic import GetCoreSchemaHandler

    failure = RuntimeError("record leaf failed")

    class Broken:
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: GetCoreSchemaHandler
        ) -> CoreSchema:
            raise failure

    class User(TypedDict):
        leaf: Broken

    with pytest.raises(RuntimeError) as captured:
        TypeAdapter[object](Schema[MapFields[User, Field[Key, Value]]])

    assert captured.value is failure


def test_unsupported_record_leaf_schema_is_a_typed_emission_failure() -> None:
    class Unsupported:
        pass

    class User(TypedDict):
        leaf: Unsupported

    with pytest.raises(
        PydanticSchemaGenerationError, match=r"emission failed \[expected_type\]"
    ):
        TypeAdapter[object](Schema[MapFields[User, Field[Key, Value]]])
