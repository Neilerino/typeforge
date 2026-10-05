"""Public slice syntax at Pydantic's endpoint and alias boundaries."""

from types import NoneType
from typing import Annotated, Literal

import pytest

from pydantic import Field, TypeAdapter, ValidationError
from typeforge import Map
from typeforge._markers import Assignable, Case, Default, Equal
from typeforge._markers import Map as CanonicalMap
from typeforge.pydantic import Input, Schema
from typeforge.pydantic._frontend import adapt_annotation


@pytest.mark.parametrize(
    ("sliced", "canonical", "raw", "expected"),
    [
        (Map[int, int:None], CanonicalMap[int, Case[int, NoneType]], None, None),
        (Map[int, int:], CanonicalMap[int, Case[int, NoneType]], None, None),
        (Map[None, :], CanonicalMap[NoneType, Case[NoneType, NoneType]], None, None),
        (Map[None, :str], CanonicalMap[NoneType, Case[NoneType, str]], "x", "x"),
        (
            Map[Literal["text"], Literal["text"] : str],
            CanonicalMap[Literal["text"], Case[Literal["text"], str]],
            "x",
            "x",
        ),
        (
            Map[int, int : Annotated[int, Field(gt=0)]],
            CanonicalMap[int, Case[int, Annotated[int, Field(gt=0)]]],
            "3",
            3,
        ),
    ],
)
def test_slice_endpoints_and_selected_metadata_match_canonical_schema(
    sliced: object, canonical: object, raw: object, expected: object
) -> None:
    selected = TypeAdapter[object](Schema[sliced])
    baseline = TypeAdapter[object](Schema[canonical])

    assert selected.json_schema() == baseline.json_schema()
    assert selected.validate_python(raw) == baseline.validate_python(raw) == expected
    assert selected.dump_json(expected) == baseline.dump_json(expected)
    assert selected.validate_json(selected.dump_json(expected)) == expected
    assert "function-" not in repr(selected.core_schema)


def test_deferred_empty_endpoints_and_unary_none_predicates() -> None:
    empty = Map[Input, :, ...:str]
    explicit = Map[Input, None:None, ...:str]
    predicate = Map[Input, Equal[None] : None, ...:str]
    canonical = CanonicalMap[Input, Case[NoneType, NoneType], Default[str]]

    assert adapt_annotation(empty).unwrap().expression == (
        adapt_annotation(explicit).unwrap().expression
    )
    for annotation in (empty, explicit, predicate, canonical):
        adapter = TypeAdapter[object](Schema[annotation])
        assert adapter.validate_python(None) is None
        assert adapter.validate_json("null") is None
        assert adapter.dump_json(None) == b"null"
        assert adapter.validate_python("text") == "text"
        with pytest.raises(ValidationError, match="string_type"):
            adapter.validate_python(1)


def test_static_and_input_selection_expand_ordinary_union_aliases() -> None:
    type Numbers = int | str

    exact = TypeAdapter[object](Schema[Map[Numbers, Numbers:bytes, ...:float]])
    expanded_subject = TypeAdapter[object](Schema[Map[Numbers, int:bytes, ...:float]])
    expanded_target = TypeAdapter[object](
        Schema[Map[int, Assignable[Numbers] : bytes, ...:float]]
    )
    observed = TypeAdapter[object](Schema[Map[Input, Numbers : int | str]])

    assert exact.validate_python("3") == b"3"
    assert expanded_subject.validate_python("3") == b"3"
    assert expanded_target.validate_python("3") == b"3"
    assert observed.validate_python("3") == "3"
    assert observed.validate_python(3) == 3
    assert observed.dump_json("3") == b'"3"'
    with pytest.raises(ValidationError, match="typeforge_map_no_match"):
        observed.validate_python(True)


def test_selected_generic_union_alias_retains_pydantic_references_and_constraints() -> (
    None
):
    type Maybe[T] = Annotated[T, Field(gt=0)] | None

    adapter = TypeAdapter[object](Schema[Map[int, int : Maybe[int]]])
    baseline = TypeAdapter[object](Maybe[int])

    for mode in ("validation", "serialization"):
        assert adapter.json_schema(mode=mode) == baseline.json_schema(mode=mode)

    repeated = TypeAdapter[object](
        tuple[Schema[Map[int, int : Maybe[int]]], Maybe[int]]
    )
    canonical = TypeAdapter[object](
        tuple[Schema[CanonicalMap[int, Case[int, Maybe[int]]]], Maybe[int]]
    )
    assert repeated.json_schema() == canonical.json_schema()
    # Schema owns its wrapper reference; the ordinary alias keeps its own.
    assert repeated.json_schema()["$defs"]["Maybe_int_"] == baseline.json_schema()
    assert adapter.validate_python("3") == 3
    assert adapter.validate_python(None) is None
    assert adapter.dump_json(3) == baseline.dump_json(3)
    with pytest.raises(ValidationError, match="greater_than"):
        adapter.validate_python(0)
