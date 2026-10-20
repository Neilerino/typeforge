from typing import Annotated, Any, Literal

import pytest

from pydantic import (
    BaseModel,
    PydanticSchemaGenerationError,
    TypeAdapter,
    ValidationError,
)
from typeforge import Is, Map, Value
from typeforge._markers import Case, Default
from typeforge._markers import Map as CanonicalMap
from typeforge.pydantic import Schema


def test_alias_capture_builds_nested_templates_and_selects_nested_maps() -> None:
    type Selected[T] = Map[
        T,
        list[Value] : tuple[Value | None, Map[Value, int : Literal["accepted"]]],
        ...:bytes,
    ]
    adapter = TypeAdapter[object](Schema[Selected[list[int]]])

    assert adapter.validate_python(["3", "accepted"]) == (3, "accepted")
    assert adapter.validate_json('[null, "accepted"]') == (None, "accepted")
    with pytest.raises(ValidationError):
        adapter.validate_python([3, "rejected"])

    assert TypeAdapter[object](Schema[Selected[set[int]]]).validate_python("3") == b"3"


def test_variadic_aliases_bind_before_reconciling_captures() -> None:
    type Packed[*Items] = Map[
        tuple[*Items], tuple[Value, Value] : list[Value], ...:bytes
    ]
    type Forward[*Items] = Packed[*Items]

    assert TypeAdapter[object](Schema[Forward[int, int]]).validate_python(["3"]) == [3]
    assert TypeAdapter[object](Schema[Forward[int, str]]).validate_python("3") == b"3"
    assert TypeAdapter[object](Schema[Packed[()]]).validate_python("3") == b"3"


def test_failed_structural_case_does_not_leak_captures() -> None:
    type Selected = Map[
        tuple[int, str],
        tuple[Value, bytes] : bytes,
        Annotated[tuple[int, Value], "opaque"] : list[Value],
    ]
    adapter = TypeAdapter[object](Schema[Selected])

    assert adapter.validate_python(["text"]) == ["text"]
    with pytest.raises(ValidationError):
        adapter.validate_python([3])


def test_alias_any_fallback_is_distinct_from_any_in_a_known_structure() -> None:
    type Selected[T] = Map[T, list[Value] : set[Value], ...:bytes]
    assert TypeAdapter[object](Schema[Selected[Any]]).validate_python("3") == b"3"
    assert TypeAdapter[object](Schema[Selected[list[Any]]]).validate_python(["3"]) == {
        "3"
    }


def test_generic_alias_fields_rebuild_and_keep_specializations_independent() -> None:
    type Selected[T] = Map[T, Is[int] : str, Is[bytes] : int]

    class Payload[T](BaseModel):
        value: Schema[Selected[T]]

    class Pair(BaseModel):
        text: Payload[int]
        number: Payload[bytes]

    value = Pair.model_validate({"text": {"value": "3"}, "number": {"value": "4"}})
    assert value.model_dump(mode="json") == {
        "text": {"value": "3"},
        "number": {"value": 4},
    }
    before = Pair.model_json_schema()
    Payload[bytes].model_rebuild(force=True)
    Payload[int].model_rebuild(force=True)
    Pair.model_rebuild(force=True)
    assert Pair.model_json_schema() == before
    with pytest.raises(ValidationError) as captured:
        Payload.model_validate({"value": "3"})

    assert captured.value.errors()[0]["type"] == "typeforge_map_no_match"
    with pytest.raises(PydanticSchemaGenerationError, match="map_no_match"):
        TypeAdapter[object](Schema[Selected[Any]])


def test_structural_capture_preserves_model_bound_typevar_serialization() -> None:
    class Detail(BaseModel):
        label: str

    class ExtraDetail(Detail):
        extra: int

    type Selected[T] = Map[list[T] | bytes, list[Value] : list[Value], ...:bytes]

    class Payload[T: Detail](BaseModel):
        value: Schema[Selected[T]]

    detail = ExtraDetail(label="x", extra=3)
    assert Payload(value=[detail]).model_dump() == {
        "value": [{"label": "x", "extra": 3}]
    }
    assert Payload[Detail](value=[detail]).model_dump() == {"value": [{"label": "x"}]}


def test_partial_generic_inheritance_substitutes_structural_alias_fields() -> None:
    type Selected[T] = Map[list[T], list[Value] : set[Value]]

    class Parent[T, U](BaseModel):
        value: Schema[Selected[T]]
        other: list[Schema[U]]

    class Child[U](Parent[int, U]):
        pass

    assert Child[str].model_validate({"value": ["3"], "other": ["x"]}).model_dump() == {
        "value": {3},
        "other": ["x"],
    }


def test_alias_defaults_bind_in_declaration_order() -> None:
    type Selected[T = int, U = list[T]] = Map[U, list[Value] : set[Value]]

    assert TypeAdapter[object](Schema[Selected]).validate_python(["3"]) == {3}
    assert TypeAdapter[object](Schema[Selected[str]]).validate_python(["3"]) == {"3"}


def test_recursive_typeforge_alias_fails_and_ordinary_recursion_delegates() -> None:
    type Recursive = Map[int, int : list[Recursive]]
    with pytest.raises(
        PydanticSchemaGenerationError, match=r"alias_cycle.*recursive aliases"
    ):
        TypeAdapter[object](Schema[Recursive])

    type Json = int | list[Json]
    adapter = TypeAdapter[object](Schema[Json])
    assert adapter.validate_python([1, [2]]) == [1, [2]]
    assert "$defs" in adapter.json_schema()


def test_missing_alias_name_preserves_model_rebuild_lifecycle() -> None:
    type Selected = Map[Later, int:str, ...:bytes]

    class Payload(BaseModel):
        value: Schema[Selected]

    assert not Payload.__pydantic_complete__
    Later = int
    assert Payload.model_rebuild()
    assert Payload.model_validate({"value": "3"}).value == "3"


def test_aliases_can_supply_patterns_and_output_templates() -> None:
    type Pattern[T] = list[T]
    type Output[T] = tuple[T, ...]
    type Selected[T] = Map[T, Pattern[Value] : Output[Value]]

    adapter = TypeAdapter[object](Schema[Selected[list[int]]])
    assert adapter.validate_python(["3", 4]) == (3, 4)


def test_variadic_alias_supports_fixed_positions_and_explicit_tuple_unpack() -> None:
    type Selected[First, *Rest, Last] = Map[
        tuple[First, *Rest, Last],
        tuple[str, Value, Value, bytes] : list[Value],
        ...:bytes,
    ]
    assert TypeAdapter[object](
        Schema[Selected[str, *tuple[int, int], bytes]]
    ).validate_python(["3"]) == [3]


def test_alias_failures_do_not_leak_bindings_between_builds() -> None:
    type Selected[T] = Map[T, int:str]
    with pytest.raises(PydanticSchemaGenerationError, match="map_no_match"):
        TypeAdapter[object](Schema[Selected[bytes]])

    assert TypeAdapter[object](Schema[Selected[int]]).validate_python("3") == "3"
    with pytest.raises(PydanticSchemaGenerationError, match="alias_arguments"):
        TypeAdapter[object](Schema[Selected[int, bytes]])


def test_nested_capture_no_match_preserves_generic_origin_only_when_needed() -> None:
    type Selected[T] = Map[list[T], list[Value] : Map[Value, Is[int] : str]]

    class Payload[T](BaseModel):
        value: Schema[Selected[T]]

    assert Payload[int].model_validate({"value": "3"}).value == "3"
    with pytest.raises(ValidationError, match="typeforge_map_no_match"):
        Payload.model_validate({"value": "3"})

    with pytest.raises(PydanticSchemaGenerationError, match="map_no_match"):
        TypeAdapter[object](Schema[Selected[Any]])


def test_ordinary_generic_alias_outputs_receive_bound_arguments() -> None:
    type Items[T] = list[T]
    type Selected[T] = Map[T, int : Items[T], ...:bytes]
    adapter = TypeAdapter[object](Schema[Selected[int]])

    assert adapter.validate_python(["3"]) == [3]
    assert adapter.json_schema() == TypeAdapter(Items[int]).json_schema()


def test_finite_unpack_expands_structural_positions() -> None:
    type Selected = Map[tuple[*tuple[int, int]], tuple[Value, Value] : list[Value]]
    assert TypeAdapter[object](Schema[Selected]).validate_python(["3"]) == [3]


def test_variadic_defaults_bind_before_structural_capture() -> None:
    type Selected[*Items = *tuple[int, int]] = Map[
        tuple[*Items], tuple[Value, Value] : list[Value], ...:bytes
    ]
    assert TypeAdapter[object](Schema[Selected]).validate_python(["3"]) == [3]
    assert TypeAdapter[object](Schema[Selected[()]]).validate_python("3") == b"3"


def test_unknown_variadic_arity_is_not_treated_as_finite_positions() -> None:
    type Selected[*Items] = Map[
        tuple[*Items], tuple[int, Value] : list[Value], ...:bytes
    ]
    for expression in (Selected, Selected[*tuple[int, ...]]):
        with pytest.raises(PydanticSchemaGenerationError, match="alias_arguments"):
            TypeAdapter[object](Schema[expression])


def test_opaque_metadata_is_not_inspected_as_a_typeforge_expression() -> None:
    type Missing = Undefined
    type Selected = Annotated[Map[int, int:str], Missing]
    type Plain = Annotated[int, Missing]

    assert TypeAdapter[object](Schema[Selected]).validate_python("3") == "3"
    assert TypeAdapter[object](Schema[Plain]).validate_python("3") == 3
    Undefined = int


def test_alias_fallbacks_use_bounds_constraints_and_defaults() -> None:
    type Bound[T: int] = Map[T, int:str, ...:bytes]
    type Constrained[T: (int, str)] = Map[T, int:bytes, str:float]
    type Defaulted[T: int = str] = Map[T, int:bytes, str:float]

    assert TypeAdapter[object](Schema[Bound]).validate_python("3") == "3"
    constrained = TypeAdapter[object](Schema[Constrained])
    assert constrained.validate_python(b"3") == b"3"
    assert constrained.validate_python(3.0) == 3.0
    assert TypeAdapter[object](Schema[Defaulted]).validate_python("3") == 3.0


def test_frontend_expands_aliases_in_canonical_branch_data() -> None:
    type Rule[T] = Case[T, str]
    type Otherwise = Default[bytes]
    type Selected[T] = CanonicalMap[T, Rule[int], Otherwise]

    assert TypeAdapter[object](Schema[Selected[int]]).validate_python("3") == "3"
    assert TypeAdapter[object](Schema[Selected[float]]).validate_python("3") == b"3"
    with pytest.raises(PydanticSchemaGenerationError, match="invalid_marker"):
        TypeAdapter[object](Schema[CanonicalMap[int, Otherwise, Rule[int]]])


def test_structural_patterns_keep_nested_fixed_unions_as_types() -> None:
    type Selected = Map[
        tuple[bytes, int | str],
        tuple[Value, int | str] : list[Value],
    ]
    assert TypeAdapter[object](Schema[Selected]).validate_python(["3"]) == [b"3"]
