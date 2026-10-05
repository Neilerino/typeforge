"""Production regression coverage promoted from the slice-syntax experiment."""

from types import NoneType
from typing import Annotated, Literal, Never, TypeVar, get_args, get_origin

import pytest

from pydantic import (
    BaseModel,
    PydanticSchemaGenerationError,
    TypeAdapter,
    ValidationError,
)
from pydantic import Field as PydanticField
from typeforge import Capture, Drop, Field, Key, Map, MapFields, OptionalField, Value
from typeforge._markers import All, Assignable, Case, Default, Equal, Not
from typeforge._markers import Map as CanonicalMap
from typeforge.pydantic import Input, Schema
from typeforge.pydantic._frontend import adapt_annotation

Item = Capture("Item")


def test_python_accepts_slices_but_does_not_substitute_inside_them() -> None:
    T = TypeVar("T")
    raw = CanonicalMap[T, int : list[T], ...:T]
    specialized = raw[int]

    assert get_args(specialized)[0] is int
    assert get_args(specialized)[1].stop == list[T]
    assert get_args(specialized)[2].stop is T
    assert CanonicalMap[int, ...:T].__parameters__ == ()


def test_eager_normalization_reuses_markers_and_preserves_substitution() -> None:
    T = TypeVar("T")
    authored = Map[T, int : list[T], ...:T]
    canonical = CanonicalMap[T, Case[int, list[T]], Default[T]]

    assert authored == canonical
    assert authored[int] == CanonicalMap[int, Case[int, list[int]], Default[int]]
    assert get_origin(authored) is CanonicalMap
    assert Map[int, ...:T].__parameters__ == (T,)
    assert adapt_annotation(authored[int]).unwrap().expression == (
        adapt_annotation(canonical[int]).unwrap().expression
    )


@pytest.mark.parametrize(
    ("selected", "canonical", "raw", "expected"),
    [
        (
            Map[int, int:str, ...:bytes],
            CanonicalMap[int, Case[int, str], Default[bytes]],
            "x",
            "x",
        ),
        (
            Map[bool, int:str, ...:bytes],
            CanonicalMap[bool, Case[int, str], Default[bytes]],
            "x",
            "x",
        ),
        (
            Map[bool, Assignable[int] : str, ...:bytes],
            CanonicalMap[bool, Case[Assignable[bool, int], str], Default[bytes]],
            "x",
            "x",
        ),
        (
            Map[int, All[Assignable[int], Not[Equal[bool]]] : str, ...:bytes],
            CanonicalMap[
                int,
                Case[All[Assignable[int, int], Not[Equal[int, bool]]], str],
                Default[bytes],
            ],
            "x",
            "x",
        ),
        (
            Map[Literal[True], True:int, ...:str],
            CanonicalMap[Literal[True], Case[Literal[True], int], Default[str]],
            "3",
            3,
        ),
        (
            Map[Literal["text"], Literal["text"] : str, ...:bytes],
            CanonicalMap[Literal["text"], Case[Literal["text"], str], Default[bytes]],
            "x",
            "x",
        ),
        (
            Map[Literal[-1], -1:int, ...:str],
            CanonicalMap[Literal[-1], Case[Literal[-1], int], Default[str]],
            "3",
            3,
        ),
        (
            Map[list[int], list[Item] : tuple[Item, ...]],
            CanonicalMap[list[int], Case[list[Item], tuple[Item, ...]]],
            ["1", 2],
            (1, 2),
        ),
        (
            Map[list[int], list[Item] : Map[Item, Equal[int] : str, ...:bytes]],
            CanonicalMap[
                list[int],
                Case[
                    list[Item],
                    CanonicalMap[Item, Case[Equal[Item, int], str], Default[bytes]],
                ],
            ],
            "x",
            "x",
        ),
        (
            Map[int, int : Map[str, Assignable[str] : bytes, ...:float]],
            CanonicalMap[
                int,
                Case[
                    int,
                    CanonicalMap[
                        str, Case[Assignable[str, str], bytes], Default[float]
                    ],
                ],
            ],
            "x",
            b"x",
        ),
    ],
)
def test_public_slices_and_canonical_data_share_the_same_semantics(
    selected: object, canonical: object, raw: object, expected: object
) -> None:
    assert adapt_annotation(selected).unwrap().expression == (
        adapt_annotation(canonical).unwrap().expression
    )
    assert TypeAdapter(Schema[selected]).validate_python(raw) == expected
    assert TypeAdapter(Schema[selected]).json_schema() == (
        TypeAdapter(Schema[canonical]).json_schema()
    )


def test_aliases_models_rebuilds_and_output_only_parameters() -> None:
    type Selected[T] = Map[T, int : list[T], ...:T]

    class Aliased[T](BaseModel):
        value: Schema[Selected[T]]

    class Direct[T](BaseModel):
        value: Schema[Map[T, int : list[T], ...:T]]
        output_only: Schema[Map[int, ... : list[T]]]

    assert Aliased[int](value=["1"]).value == [1]
    assert Aliased[str](value="x").value == "x"
    assert Direct[int](value=["1"], output_only=["2"]).output_only == [2]
    assert Direct[str](value="x", output_only=["y"]).output_only == ["y"]
    Direct[int].model_rebuild(force=True)
    Aliased[int].model_rebuild(force=True)
    assert Direct[int](value=["3"], output_only=["4"]).value == [3]
    assert Aliased[int](value=["5"]).value == [5]


def test_input_selection_preserves_first_match_and_does_not_retry_validation() -> None:
    adapter = TypeAdapter(
        Schema[Map[Input, str:int, Assignable[int] : float, ...:bytes]]
    )

    assert adapter.validate_python("3") == 3
    assert adapter.validate_python(True) == 1.0
    assert type(adapter.validate_python(3)) is float
    with pytest.raises(ValidationError):
        adapter.validate_python("bad")


def test_input_literals_distinguish_bool_from_int_and_preserve_no_match() -> None:
    adapter = TypeAdapter(Schema[Map[Input, True:str, 1:int]])
    with pytest.raises(ValidationError, match="typeforge_map_no_match"):
        adapter.validate_python(False)

    assert (
        TypeAdapter(Schema[Map[Input, True:bool, 1:int]]).validate_python(True) is True
    )
    assert (
        type(TypeAdapter(Schema[Map[Input, True:bool, 1:int]]).validate_python(1))
        is int
    )


def test_record_fields_and_nested_outputs_use_unchanged_runtime_frontend() -> None:
    from typing import TypedDict

    class User(TypedDict):
        name: str
        password: str
        age: int

    type Public[T] = MapFields[
        T,
        Map[
            Key,
            Literal["password"] : Drop,
            Literal["name"] : OptionalField[Literal["display_name"], Value],
            ... : Field[Key, Value],
        ],
    ]

    adapter = TypeAdapter(Schema[Public[User]])
    assert adapter.validate_python({"age": "3"}) == {"age": 3}
    assert adapter.validate_python({"display_name": "Ada", "age": 3}) == {
        "display_name": "Ada",
        "age": 3,
    }


def test_selected_annotations_stay_with_pydantic() -> None:
    adapter = TypeAdapter(Schema[Map[int, int : Annotated[int, PydanticField(gt=0)]]])
    assert adapter.validate_python("3") == 3
    with pytest.raises(ValidationError):
        adapter.validate_python(-1)


@pytest.mark.parametrize(
    ("annotation", "message"),
    [
        (Map[str, int:bytes], "map_no_match"),
        (Map[int, int:Never], "expected_type"),
        (Map[Input, list[int] : bytes], "unsupported_runtime_pattern"),
    ],
)
def test_existing_failure_policies_still_apply(
    annotation: object, message: str
) -> None:
    with pytest.raises(PydanticSchemaGenerationError, match=message):
        TypeAdapter(Schema[annotation])


def test_none_type_is_an_unambiguous_runtime_alternative() -> None:
    adapter = TypeAdapter(Schema[Map[Input, NoneType:NoneType, ...:str]])
    assert adapter.validate_python(None) is None
    assert adapter.validate_python("x") == "x"


def test_predicate_alias_is_bound_by_the_frontend_after_construction() -> None:
    type Numeric = Assignable[int]

    assert (
        TypeAdapter(Schema[Map[int, Numeric:str, ...:bytes]]).validate_python("x")
        == "x"
    )
