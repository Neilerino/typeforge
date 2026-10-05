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
from typeforge import Capture, Doc, Drop, Field, Fields, Map, Record
from typeforge._markers import Equal
from typeforge.pydantic import Schema

Item = Capture("Item")


def test_record_transforms_validate_rename_drop_and_preserve_leaf_constraints() -> None:
    class User(TypedDict):
        name: str
        count: Annotated[int, PydanticField(gt=0)]
        password: str

    type Public[T] = Record(
        Map[
            field.name,
            Equal[field.name, Literal["password"]] : Drop,
            Equal[field.name, Literal["name"]] : Field(
                name="display_name", type=field.type, required=False
            ),
            ... : Field(name=field.name, type=field.type),
        ]
        for field in Fields[T]
    )

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

    type Public[T] = Annotated[
        Record(
            Map[field.name, ... : Field(name=field.name, type=field.type)]
            for field in Fields[T]
        ),
        Doc("Public record"),
    ]

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
        value: Schema[
            Record(
                Map[field.name, ... : Field(name=field.name, type=field.type)]
                for field in Fields[T]
            )
        ]

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

    type Converted[T] = Record(
        Field(name=field.name, type=Map[field.type, list[Item] : set[Item]])
        for field in Fields[Items[T]]
    )

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
    adapter = TypeAdapter[object](
        Schema[
            Record(
                Field(name=field.name, type=field.type, readonly=True)
                for field in Fields[Payload]
            )
        ]
    )
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
        int : Annotated[
            Record(Field(name=field.name, type=field.type) for field in Fields[User]),
            Doc("Selected record"),
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

    type Selected = Annotated[
        Record(Field(name=field.name, type=field.type) for field in Fields[User]),
        AfterValidator(inner),
    ]
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
        left: Schema[
            Record(
                Field(name=field.name, type=field.type) for field in Fields[Left.User]
            )
        ]
        right: Schema[
            Record(
                Field(name=field.name, type=field.type) for field in Fields[Right.User]
            )
        ]
        renamed: Schema[
            Record(
                Field(name="renamed", type=Literal["fixed"])
                for field in Fields[Left.User]
            )
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
            TypeAdapter[object](
                Schema[
                    Record(
                        Field(name=field.name, type=field.type)
                        for field in Fields[record]
                    )
                ]
            )

    with pytest.raises(PydanticSchemaGenerationError, match="unsupported_record"):

        class Payload[T](BaseModel):
            value: Schema[
                Record(Field(name=field.name, type=T) for field in Fields[int])
            ]


@pytest.mark.parametrize(
    ("transform", "code"),
    [
        ('Field(name="same", type=field.type)', "duplicate_field"),
        ("field.type", "expected_field"),
        ("Field(name=Literal[3], type=field.type)", "expected_field_name"),
    ],
)
def test_invalid_field_transforms_fail_before_validation(
    transform: str, code: str
) -> None:
    class User(TypedDict):
        left: int
        right: str

    with pytest.raises(PydanticSchemaGenerationError, match=code):
        TypeAdapter[object](
            Schema[
                Record(
                    eval(transform, globals(), {"field": field})
                    for field in Fields[User]
                )
            ]
        )


def test_partial_generic_records_and_defaults_follow_pydantic_lifecycle() -> None:
    class User(TypedDict):
        count: int

    class Parent[T, U](BaseModel):
        value: Schema[
            Record(
                Map[field.name, ... : Field(name=field.name, type=field.type)]
                for field in Fields[T]
            )
        ]
        other: U

    class Child[U](Parent[User, U]):
        pass

    class Defaulted[T = User](BaseModel):
        value: Schema[
            Record(
                Map[field.name, ... : Field(name=field.name, type=field.type)]
                for field in Fields[T]
            )
        ]

    class Bound[T: User](BaseModel):
        value: Schema[
            Record(
                Map[field.name, ... : Field(name=field.name, type=field.type)]
                for field in Fields[T]
            )
        ]

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

    type Selected[T] = Record(
        Field(name=field.name, type=Map[field.type, list[Item] : set[Item]])
        for field in Fields[T]
    )
    result = TypeAdapter[object](Schema[Selected[Child[str]]]).validate_python(
        {"first": ["3"], "second": ["x"]}
    )
    assert result == {"first": {3}, "second": {"x"}}


def test_missing_record_field_name_can_be_resolved_by_model_rebuild() -> None:
    class User(TypedDict):
        field: Later

    class Payload(BaseModel):
        value: Schema[
            Record(Field(name=field.name, type=field.type) for field in Fields[User])
        ]

    assert not Payload.__pydantic_complete__
    Later = int
    assert Payload.model_rebuild()
    assert Payload.model_validate({"value": {"field": "3"}}).model_dump() == {
        "value": {"field": 3}
    }


def test_resolved_record_outputs_need_no_validation_callbacks() -> None:
    class User(TypedDict):
        value: int

    adapter = TypeAdapter[object](
        Schema[
            Record(Field(name=field.name, type=field.type) for field in Fields[User])
        ]
    )
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
        value: Schema[
            Record(Field(name=field.name, type=field.type) for field in Fields[Item[T]])
        ]

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
        TypeAdapter[object](
            Schema[
                Record(
                    Field(name=field.name, type=field.type) for field in Fields[User]
                )
            ]
        )

    assert captured.value is failure


def test_unsupported_record_leaf_schema_is_a_typed_emission_failure() -> None:
    class Unsupported:
        pass

    class User(TypedDict):
        leaf: Unsupported

    with pytest.raises(
        PydanticSchemaGenerationError, match=r"emission failed \[expected_type\]"
    ):
        TypeAdapter[object](
            Schema[
                Record(
                    Field(name=field.name, type=field.type) for field in Fields[User]
                )
            ]
        )
