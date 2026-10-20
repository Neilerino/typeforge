from typing import Annotated, Literal, TypedDict

import pytest
from returns.result import Failure

from pydantic import PydanticSchemaGenerationError, TypeAdapter, ValidationError
from typeforge import Capture, Field, Fields, Map, Record
from typeforge import semantics as s
from typeforge._markers import All, Assignable, Equal, Not
from typeforge._markers import Any as AnyCondition
from typeforge.pydantic import Input, Schema
from typeforge.pydantic._frontend import adapt_annotation

Item = Capture("Item")


def test_unary_predicate_alias_binds_the_consuming_subject() -> None:
    type Numeric = Assignable[int]

    assert (
        TypeAdapter(Schema[Map[int, Numeric:str, ...:bytes]]).validate_python("x")
        == "x"
    )
    assert (
        TypeAdapter(Schema[Map[str, Numeric:str, ...:bytes]]).validate_python("x")
        == b"x"
    )


def test_generic_chained_and_compound_predicates_bind_each_nested_map() -> None:
    type Is[T] = Equal[T]
    type Alias[T] = Is[T]
    type Numeric = All[Assignable[int], Not[Alias[bool]]]
    type Either = AnyCondition[Alias[int], Alias[bytes]]

    annotation = Map[int, Numeric : Map[bytes, Either:str, ...:float], ...:bytes]
    assert TypeAdapter(Schema[annotation]).validate_python("x") == "x"
    assert (
        TypeAdapter(Schema[Map[bool, Numeric:str, ...:bytes]]).validate_python("x")
        == b"x"
    )
    inline = Map[
        int,
        All[Assignable[int], Not[Equal[bool]]] : Map[
            bytes, AnyCondition[Equal[int], Equal[bytes]] : str, ...:float
        ],
        ...:bytes,
    ]
    assert (
        adapt_annotation(annotation).unwrap().expression
        == adapt_annotation(inline).unwrap().expression
    )


def test_explicit_operands_are_not_rebound() -> None:
    type Explicit[T] = Equal[T, bytes]

    assert (
        TypeAdapter(Schema[Map[int, Explicit[bytes] : str, ...:float]]).validate_python(
            "x"
        )
        == "x"
    )


def test_same_named_parameters_and_sibling_alias_uses_keep_their_bindings() -> None:
    type Is[T] = Equal[T]
    type Select[T] = Map[T, Is[T] : tuple[T, Map[bytes, Is[bytes] : str]]]

    adapter = TypeAdapter(Schema[tuple[Select[int], Select[str]]])
    assert adapter.validate_python(((1, "a"), ("b", "c"))) == ((1, "a"), ("b", "c"))


def test_malformed_predicate_aliases_fail_at_the_typed_frontend_boundary() -> None:
    type Is[T] = Equal[T]
    type Bad = Equal[int, str, bytes]

    for selector, code in ((Is[int, str], "alias_arguments"), (Bad, "invalid_marker")):
        result = adapt_annotation(Map[int, selector:bytes])
        assert isinstance(result, Failure)
        assert result.failure().code == code


def test_predicate_aliases_bind_input_before_validation_without_retries() -> None:
    type Text = Equal[str]

    adapter = TypeAdapter(Schema[Map[Input, Text:int, ...:str]])
    assert adapter.validate_python("3") == 3
    with pytest.raises(ValidationError):
        adapter.validate_python("bad")


def test_field_and_capture_subjects_are_independent() -> None:
    type Integer = Equal[int]
    type Name = Equal[Literal["value"]]

    class Row(TypedDict):
        value: int

    fields = Record(
        Map[
            field.name,
            Name : Field(name=field.name, type=Map[field.type, Integer:str, ...:bytes]),
        ]
        for field in Fields[Row]
    )
    assert TypeAdapter(Schema[fields]).validate_python({"value": "x"}) == {"value": "x"}
    captured = Map[list[int], list[Item] : Map[Item, Integer:str, ...:bytes]]
    assert TypeAdapter(Schema[captured]).validate_python("x") == "x"


def test_annotated_alias_retains_metadata_and_authored_origin() -> None:
    type Numeric = Assignable[int]

    metadata = object()
    selected = Annotated[Numeric, metadata]
    adapted = adapt_annotation(Map[int, selected:str]).unwrap()
    assert isinstance(adapted.expression, s.MapExpression)
    test = adapted.expression.cases[0].test
    assert isinstance(test, s.AnnotatedExpression)
    assert adapted.origins[id(test)] is selected
    assert test.metadata[0].annotation is metadata


@pytest.mark.parametrize("position", ["standalone", "output", "operand"])
def test_unary_alias_is_unbound_outside_selector_positions(position: str) -> None:
    type Numeric = Assignable[int]

    annotation = {
        "standalone": Numeric,
        "output": Map[int, int:Numeric],
        "operand": Map[int, Equal[Numeric, int] : str],
    }[position]
    with pytest.raises(PydanticSchemaGenerationError, match="Map selector subject"):
        TypeAdapter(Schema[annotation])


def test_alias_cycles_and_failure_recovery_preserve_the_boundary() -> None:
    type Recursive = All[Equal[int], Recursive]
    type Valid = Equal[str]

    failed = adapt_annotation(Map[int, Recursive:str])
    assert isinstance(failed, Failure)
    assert failed.failure().code == "alias_cycle"
    assert TypeAdapter(Schema[Map[str, Valid:bytes]]).validate_python("x") == b"x"


@pytest.mark.parametrize("subject", [int, str, bool, int | str])
def test_union_predicate_alias_matches_the_inline_whole_subject(
    subject: object,
) -> None:
    type Numeric = Assignable[int | str]

    aliased = Map[subject, Numeric:bytes, ...:float]
    inline = Map[subject, Assignable[int | str] : bytes, ...:float]
    assert (
        adapt_annotation(aliased).unwrap().expression
        == adapt_annotation(inline).unwrap().expression
    )
    assert (
        TypeAdapter(Schema[aliased]).json_schema()
        == TypeAdapter(Schema[inline]).json_schema()
    )


def test_literal_alias_targets_use_the_existing_selector_normalizer() -> None:
    type One = Equal[1]
    type Empty = Equal[None]
    type Bad = Equal["text"]  # noqa: F821 - deliberately invalid bare string selector

    assert TypeAdapter(Schema[Map[Literal[1], One:str]]).validate_python("x") == "x"
    assert TypeAdapter(Schema[Map[None, Empty:str]]).validate_python("x") == "x"
    with pytest.raises(PydanticSchemaGenerationError, match="Literal"):
        TypeAdapter(Schema[Map[str, Bad:bytes]])
