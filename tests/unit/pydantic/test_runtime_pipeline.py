from typing import Annotated, Any, Never

import pytest
from pydantic_core import CoreSchema

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    GetCoreSchemaHandler,
    PydanticSchemaGenerationError,
    TypeAdapter,
    ValidationError,
)
from typeforge import All, Assignable, Case, Default, Equal, Key, Map, Not
from typeforge.pydantic import Schema


def test_generic_no_default_map_specializes_and_rejects_unmatched_any() -> None:
    class Payload[T](BaseModel):
        value: Schema[Map[T, Case[int, str], Case[bytes, int]]]

    assert Payload[int].model_validate({"value": "3"}).value == "3"
    assert Payload[bytes].model_validate({"value": "3"}).value == 3
    with pytest.raises(ValidationError) as captured:
        Payload.model_validate({"value": "3"})

    issue = captured.value.errors()[0]
    assert issue["type"] == "typeforge_map_no_match"
    assert issue["loc"] == ("value",)
    assert "Any" in issue["msg"]
    definitions = Payload.model_json_schema()["$defs"]
    assert any(definition.get("not") == {} for definition in definitions.values())
    Payload[int].model_rebuild(force=True)
    assert Payload[int].model_validate({"value": "3"}).value == "3"


def test_fallback_bounds_defaults_and_constraints_select_map_outputs() -> None:
    class Bound[T: int](BaseModel):
        value: Schema[Map[T, Case[int, str], Default[bytes]]]

    class Defaulted[T = int](BaseModel):
        value: Schema[Map[T, Case[int, str], Default[bytes]]]

    class Constrained[T: (int, bytes)](BaseModel):
        value: Schema[Map[T, Case[int, str], Case[bytes, float], Default[bool]]]

    class DefaultBeforeBound[T: int = bool](BaseModel):
        value: Schema[Map[T, Case[bool, str], Case[int, bytes]]]

    assert Bound.model_validate({"value": "3"}).value == "3"
    assert Defaulted.model_validate({"value": "3"}).value == "3"
    assert Constrained.model_validate({"value": "3"}).value == "3"
    assert Constrained.model_validate({"value": 3.5}).value == 3.5
    assert DefaultBeforeBound.model_validate({"value": "3"}).value == "3"
    assert Defaulted[bytes].model_validate({"value": "3"}).value == b"3"


def test_any_fallback_follows_exact_cases_and_authored_default() -> None:
    class Payload[T](BaseModel):
        value: Schema[Map[T, Case[int, str], Default[bytes]]]

    class ExplicitAny[T](BaseModel):
        value: Schema[Map[T, Case[int, bytes], Case[Any, str]]]

    assert Payload.model_validate({"value": "3"}).value == b"3"
    assert Payload[Any].model_validate({"value": "3"}).value == b"3"
    assert ExplicitAny.model_validate({"value": "3"}).value == "3"
    assert ExplicitAny[int].model_validate({"value": "3"}).value == b"3"


@pytest.mark.parametrize("first", [int, bytes])
def test_partial_inheritance_and_specializations_keep_field_schemas_isolated(
    first: type,
) -> None:
    class Payload[T, U](BaseModel):
        value: Schema[Map[T, Case[int, str], Case[bytes, int]]]
        items: list[Schema[U]]

    class Partial[U](Payload[int, U]):
        pass

    # Build in both orders to expose state retained across hook calls.
    Payload[first, int]

    class Envelope(BaseModel):
        text: Payload[int, int]
        number: Payload[bytes, str]

    raw = {
        "text": {"value": "3", "items": ["4"]},
        "number": {"value": "3", "items": ["4"]},
    }
    adapter = TypeAdapter(Envelope)
    expected = {
        "text": {"value": "3", "items": [4]},
        "number": {"value": 3, "items": ["4"]},
    }
    result = adapter.validate_python(raw)
    assert result.model_dump() == expected
    assert adapter.validate_json(adapter.dump_json(result)).model_dump() == expected
    for mode in ("validation", "serialization"):
        schema = Envelope.model_json_schema(mode=mode)
        Envelope.model_rebuild(force=True)
        assert Envelope.model_json_schema(mode=mode) == schema

    assert Partial[int](value="3", items=["4"]).model_dump() == {
        "value": "3",
        "items": [4],
    }


def test_generic_output_does_not_defer_an_unrelated_concrete_no_match() -> None:
    with pytest.raises(PydanticSchemaGenerationError, match=r"\[map_no_match\]"):

        class Payload[T](BaseModel):
            value: Schema[Map[Any, Case[int, T]]]


def test_selected_typevar_retains_pydantic_model_bound_serialization() -> None:
    class Detail(BaseModel):
        label: str

    class Extra(Detail):
        extra: int

    class Payload[T: Detail](BaseModel):
        value: Schema[Map[T, Case[Equal[T, T], T]]]

    detail = Extra(label="x", extra=3)
    assert Payload.model_validate({"value": detail}).model_dump() == {
        "value": {"label": "x", "extra": 3}
    }
    assert Payload[Detail].model_validate({"value": detail}).model_dump() == {
        "value": {"label": "x"}
    }


@pytest.mark.parametrize(
    "expression",
    [Map[Any, Case[int, str]], Map[int, Case[int, Map[Any, Case[bytes, str]]]]],
)
def test_direct_and_nested_no_match_report_authored_map(expression: object) -> None:
    with pytest.raises(
        PydanticSchemaGenerationError, match=r"\[map_no_match\].*Map.*Any"
    ):
        TypeAdapter[object](Schema[expression])


@pytest.mark.parametrize(
    "expression", [Map[int, Case[int, Never]], Map[Any, Default[Never]]]
)
def test_selected_never_is_not_misreported_as_no_match(expression: object) -> None:
    with pytest.raises(PydanticSchemaGenerationError) as captured:
        TypeAdapter[object](Schema[expression])

    assert "[expected_type]" in str(captured.value)
    assert "[map_no_match]" not in str(captured.value)


def test_no_match_stops_evaluation_before_later_operand_failure() -> None:
    with pytest.raises(PydanticSchemaGenerationError, match=r"\[map_no_match\]"):
        TypeAdapter[object](
            Schema[Map[int, Case[Equal[Map[Any, Case[int, str]], Key], str]]]
        )


def test_conditions_short_circuit_and_union_subjects_share_evaluation() -> None:
    adapter = TypeAdapter[object](
        Schema[
            Map[
                int | bytes,
                Case[All[Assignable[int, object], Not[Equal[int, bytes]]], str],
                Case[Equal[Key, Key], Never],
            ]
        ]
    )

    assert adapter.validate_python("3") == "3"


def test_ordinary_types_and_metadata_delegate_without_added_validation_callbacks() -> (
    None
):
    adapter = TypeAdapter[object](Schema[list[int]])
    assert adapter.validate_python(["3"]) == [3]
    assert adapter.json_schema() == {"items": {"type": "integer"}, "type": "array"}

    def has_callback(value: object) -> bool:
        if isinstance(value, dict):
            return str(value.get("type", "")).startswith("function-") or any(
                has_callback(item) for item in value.values()
            )

        if isinstance(value, list):
            return any(has_callback(item) for item in value)

        return False

    assert not has_callback(adapter.core_schema)
    selected = TypeAdapter[object](Schema[Map[int, Case[int, list[int]]]])
    assert not has_callback(selected.core_schema)

    calls: list[str] = []

    def inner(value: int) -> int:
        calls.append("inner")
        return value + 1

    def outer(value: int) -> int:
        calls.append("outer")
        return value * 2

    wrapped = TypeAdapter[object](
        Annotated[
            Schema[Annotated[Map[int, Case[int, int]], AfterValidator(inner)]],
            AfterValidator(outer),
        ]
    )
    assert wrapped.validate_python("3") == 8
    assert calls == ["inner", "outer"]

    positive = TypeAdapter[object](Schema[Annotated[int, Field(gt=0)]])
    with pytest.raises(ValidationError):
        positive.validate_python(0)


def test_unexpected_schema_hook_failure_propagates_with_identity() -> None:
    failure = RuntimeError("application hook failed")

    class Broken:
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: GetCoreSchemaHandler
        ) -> CoreSchema:
            raise failure

    with pytest.raises(RuntimeError) as captured:
        TypeAdapter[object](Schema[Broken])

    assert captured.value is failure


def test_resolved_structural_maps_need_no_validation_callbacks() -> None:
    adapter = TypeAdapter[object](Schema[Map[int, Case[int, list[int]]]])
    assert adapter.validate_python(["3"]) == [3]

    from typeforge import Value

    type Selected[T] = Map[T, Case[list[Value], tuple[Value, ...]]]
    structural = TypeAdapter[object](Schema[Selected[list[int]]])
    assert structural.validate_python(["3"]) == (3,)
    assert "function-" not in repr(structural.core_schema)
