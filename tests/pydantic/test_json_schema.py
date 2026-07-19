from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, TypeAdapter
from typeforge import Case, Doc, Drop, Equal, Field, If, Key, Map, MapFields, Value
from typeforge.pydantic import Schema


class User(TypedDict):
    name: str
    password: str


type Public[T] = Annotated[
    MapFields[
        T,
        If[
            Equal[Key, Literal["password"]],
            Drop,
            Field[Key, Value],
        ],
    ],
    Doc("A public user without private credentials."),
]

type DescribedInteger = Annotated[
    Map[int, Case[int, int]],
    Doc("An integer selected by a Typeforge expression."),
]


def test_map_fields_json_schema_has_stable_definition_and_documentation() -> None:
    class Pair(BaseModel):
        first: Schema[Public[User]]
        second: Schema[Public[User]]

    schema = Pair.model_json_schema()

    assert len(schema["$defs"]) == 1
    definition_name, definition = next(iter(schema["$defs"].items()))
    assert definition["description"] == "A public user without private credentials."
    assert definition["required"] == ["name"]
    assert set(definition["properties"]) == {"name"}
    reference = f"#/$defs/{definition_name}"
    assert schema["properties"]["first"]["$ref"] == reference
    assert schema["properties"]["second"]["$ref"] == reference


def test_recursive_non_typeforge_alias_delegates_to_pydantic() -> None:
    type Json = int | list[Json]
    adapter = TypeAdapter(Schema[Json])

    assert adapter.validate_python(["1", [2]]) == [1, [2]]
    schema = adapter.json_schema()
    assert "$defs" in schema


def test_doc_metadata_describes_an_ordinary_resolved_type() -> None:
    adapter = TypeAdapter(Annotated[Schema[int], Doc("A positive count.")])

    assert adapter.json_schema()["description"] == "A positive count."


def test_doc_metadata_describes_a_resolved_typeforge_expression() -> None:
    adapter = TypeAdapter(Schema[DescribedInteger])

    assert adapter.json_schema()["description"] == (
        "An integer selected by a Typeforge expression."
    )


def test_synthesized_record_refs_distinguish_qualified_input_names() -> None:
    class Left:
        class User(TypedDict):
            left: int

    class Right:
        class User(TypedDict):
            right: str

    class Pair(BaseModel):
        left: Schema[Public[Left.User]]
        right: Schema[Public[Right.User]]

    schema = Pair.model_json_schema()
    left_ref = schema["properties"]["left"]["$ref"]
    right_ref = schema["properties"]["right"]["$ref"]

    assert left_ref != right_ref
    assert set(schema["$defs"][left_ref.rsplit("/", 1)[1]]["properties"]) == {"left"}
    assert set(schema["$defs"][right_ref.rsplit("/", 1)[1]]["properties"]) == {"right"}
