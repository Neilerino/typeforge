"""Public runtime construction contracts for slice Map."""

from types import NoneType
from typing import Annotated, Literal, Never, TypeVar, get_args, get_origin

import pytest

from pydantic import BaseModel, PydanticSchemaGenerationError, TypeAdapter
from typeforge import All, Assignable, Equal, Map, Not, Value
from typeforge._markers import Case, Default
from typeforge._markers import Map as CanonicalMap
from typeforge.pydantic import Schema


def test_output_only_parameter_is_discovered_and_specialized() -> None:
    T = TypeVar("T")
    expression = Map[int, int : list[T], ...:bytes]

    assert expression.__parameters__ == (T,)
    specialized = expression[str]
    assert get_origin(specialized) is CanonicalMap
    assert get_args(specialized) == (int, Case[int, list[str]], Default[bytes])
    assert TypeAdapter(Schema[specialized]).validate_python(["x"]) == ["x"]


@pytest.mark.parametrize(
    "expression",
    [Map[int, int:None], Map[int, int:], Map[int, ...:None], Map[int, ...:]],
)
def test_none_and_empty_outputs_denote_the_none_type(expression: object) -> None:
    branch = get_args(expression)[1]
    assert get_args(branch)[-1] is NoneType
    assert TypeAdapter(Schema[expression]).validate_python(None) is None


def test_empty_selectors_are_none_and_explicit_none_steps_are_inert() -> None:
    assert Map[None, :str] == Map[None, None:str]
    assert Map[None, :] == Map[None, None:None]
    assert get_args(get_args(Map[None, :str])[1])[0] is NoneType
    assert Map[int, int:str:None] == Map[int, int:str]
    assert TypeAdapter(Schema[Map[None, :str]]).validate_python("x") == "x"


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ((), "subject"),
        ((int,), "branch"),
        ((int, str), "selector: output"),
        ((int, slice(int, str, bytes)), "step"),
        ((int, slice(Ellipsis, str), slice(int, bytes)), "fallback"),
        ((int, slice(Ellipsis, str), slice(Ellipsis, bytes)), "fallback"),
    ],
)
def test_malformed_subscriptions_fail_at_construction(
    parameters: tuple[object, ...],
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        Map[parameters]


def test_inline_predicates_bind_locally_and_preserve_explicit_operands() -> None:
    expression = Map[
        int,
        All[Assignable[int], Not[Equal[bool]]] : Map[bytes, Equal[bytes] : str],
        Equal[float, str] : bytes,
    ]
    assert (
        expression
        == CanonicalMap[
            int,
            Case[
                All[Assignable[int, int], Not[Equal[int, bool]]],
                CanonicalMap[bytes, Case[Equal[bytes, bytes], str]],
            ],
            Case[Equal[float, str], bytes],
        ]
    )
    assert TypeAdapter(Schema[expression]).validate_python("x") == "x"


@pytest.mark.parametrize("selector", [True, 1, -1, b"x"])
def test_literal_selector_sugar_preserves_literal_identity(selector: object) -> None:
    assert (
        Map[Literal[selector], selector:str]
        == CanonicalMap[Literal[selector], Case[Literal[selector], str]]
    )
    assert (
        Map[Literal[selector], Equal[selector] : str]
        == CanonicalMap[
            Literal[selector], Case[Equal[Literal[selector], Literal[selector]], str]
        ]
    )


@pytest.mark.parametrize("selector", ["text", Equal["text"], All[Equal["text"]]])
def test_string_selectors_require_literal(selector: object) -> None:
    with pytest.raises(TypeError, match="Literal"):
        Map[str, selector:bytes]


def test_explicit_literal_string_selectors_are_supported() -> None:
    annotation = Map[Literal["text"], Literal["text"] : str]
    assert TypeAdapter(Schema[annotation]).validate_python("x") == "x"


def test_union_parameters_survive_discovery_specialization_and_model_rebuild() -> None:
    T = TypeVar("T")
    expression = Map[int, T | str : list[T | None], ...:T] | bytes
    inner = get_args(expression)[0]
    assert inner.__parameters__ == (T,)
    assert (
        inner[float]
        == CanonicalMap[int, Case[float | str, list[float | None]], Default[float]]
    )

    type Output[T] = Map[int, int : list[T | None]] | bytes

    class Payload[T](BaseModel):
        alias: Schema[Output[T]]
        direct: Schema[Map[T, int : list[T | None], ...:T]]

    specialized = Payload[int]
    for _ in range(2):
        model = specialized(alias=["1", None], direct=["2", None])
        assert model.alias == [1, None]
        assert model.direct == [2, None]
        specialized.model_rebuild(force=True)


def test_selector_only_parameters_and_scope_identity_are_preserved() -> None:
    T = TypeVar("T")
    other = TypeVar("T")
    expression = Map[int, Equal[T] : str, other:bytes, ...:float]
    assert expression.__parameters__ == (T, other)
    assert (
        expression[int, str]
        == CanonicalMap[
            int, Case[Equal[int, int], str], Case[str, bytes], Default[float]
        ]
    )


def test_construction_preserves_order_metadata_and_structural_capture() -> None:
    metadata = object()
    output = Annotated[tuple[Value, ...], metadata]
    expression = Map[list[int], list[Value] : output, list[Value] : bytes]
    assert get_args(expression)[1:] == (
        Case[list[Value], output],
        Case[list[Value], bytes],
    )
    assert get_args(get_args(get_args(expression)[1])[1])[-1] is metadata
    assert TypeAdapter(Schema[expression]).validate_python(["1"]) == (1,)


def test_canonical_equality_hashing_and_inert_fallback() -> None:
    expression = Map[int, int:str, ...:bytes]
    canonical = CanonicalMap[int, Case[int, str], Default[bytes]]
    assert expression == canonical
    assert hash(expression) == hash(canonical)
    assert {expression: "selected"}[canonical] == "selected"
    assert get_args(Map.__value__)[0] is object
    ordinary = TypeAdapter(expression)
    value = object()
    assert ordinary.validate_python(value) is value


def test_missing_fallback_and_selected_never_are_distinct() -> None:
    unmatched = Map[str, int:bytes]
    selected = Map[int, int:Never]
    assert get_args(unmatched) == (str, Case[int, bytes])
    assert get_args(selected) == (int, Case[int, Never])
    for annotation, error in ((unmatched, "map_no_match"), (selected, "expected_type")):
        with pytest.raises(PydanticSchemaGenerationError, match=error):
            TypeAdapter(Schema[annotation])


def test_construction_leaves_lazy_aliases_and_semantic_failures_unevaluated() -> None:
    def forbidden() -> object:
        raise AssertionError("Constructing Map must not evaluate authored aliases")

    type Lazy = forbidden()

    annotation = Map[int, Lazy : Equal[int], ...:Lazy]
    assert get_args(annotation) == (int, Case[Lazy, Equal[int]], Default[Lazy])
    # Output predicates are not implicitly bound; only selector positions bind.
    assert get_args(get_args(annotation)[1])[1] == Equal[int]
