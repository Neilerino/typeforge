from typing import Annotated, Literal

import pytest

from pydantic import AfterValidator, TypeAdapter, ValidationError
from typeforge import Key, Map
from typeforge._markers import All, Assignable, Equal
from typeforge.pydantic import Input, Schema


def test_input_selects_first_case_and_never_retries_after_output_failure() -> None:
    calls: list[str] = []

    def first(value: int) -> int:
        calls.append("first")
        return value

    def later(value: str) -> str:
        calls.append("later")
        return value

    type Selected = Map[
        Input,
        str : Annotated[int, AfterValidator(first)],
        str : Annotated[str, AfterValidator(later)],
        ... : Annotated[str, AfterValidator(later)],
    ]
    adapter = TypeAdapter[object](Schema[Selected])

    assert adapter.validate_python("3") == 3
    assert calls == ["first"]
    calls.clear()
    with pytest.raises(ValidationError) as captured:
        adapter.validate_python("not-an-int")

    assert captured.value.errors()[0]["type"] == "int_parsing"
    assert calls == []


@pytest.mark.parametrize("raw", [True, 3.0, None])
def test_input_no_match_has_stable_code_and_original_input(raw: object) -> None:
    adapter = TypeAdapter[object](Schema[Map[Input, int:str]])

    with pytest.raises(ValidationError) as captured:
        adapter.validate_python(raw)

    issue = captured.value.errors()[0]
    assert issue["type"] == "typeforge_map_no_match"
    assert issue["input"] is raw


def test_input_predicate_assignability_can_accept_a_subclass() -> None:
    adapter = TypeAdapter[object](
        Schema[Map[Input, Assignable[Input, int] : int, ...:str]]
    )

    assert adapter.validate_python(True) == 1
    assert adapter.validate_python("3") == "3"


def test_input_union_and_annotated_patterns_match_raw_types() -> None:
    adapter = TypeAdapter[object](
        Schema[Map[Input, Annotated[int | str, "description"] : int]]
    )

    assert adapter.validate_python(3) == 3
    assert adapter.validate_python("3") == 3
    assert adapter.validate_json('"3"') == 3
    with pytest.raises(ValidationError) as captured:
        adapter.validate_python(True)

    assert captured.value.errors()[0]["type"] == "typeforge_map_no_match"


def test_input_literal_patterns_match_values_before_output_coercion() -> None:
    adapter = TypeAdapter[object](Schema[Map[Input, Literal["3"] : int, ...:str]])

    assert adapter.validate_python("3") == 3
    assert adapter.validate_python("4") == "4"
    assert adapter.validate_json('"3"') == 3


def test_input_predicate_short_circuit_skips_unbound_operand() -> None:
    adapter = TypeAdapter[object](
        Schema[
            Map[
                Input,
                All[Equal[Input, int], Equal[Key, Key]] : bytes,
                ...:str,
            ]
        ]
    )

    assert adapter.validate_python("text") == "text"


def test_nested_input_map_observes_raw_value_before_outer_output_validation() -> None:
    adapter = TypeAdapter[object](
        Schema[
            Map[
                Input,
                str : Map[Input, str:int, ...:bytes],
                ...:float,
            ]
        ]
    )

    assert adapter.validate_python("3") == 3
    assert type(adapter.validate_python(3)) is float


def test_unexpected_output_validator_exception_propagates_unchanged() -> None:
    failure = RuntimeError("application validator failed")

    def fail(value: int) -> int:
        raise failure

    adapter = TypeAdapter[object](
        Schema[Map[Input, str : Annotated[int, AfterValidator(fail)]]]
    )

    with pytest.raises(RuntimeError) as captured:
        adapter.validate_python("3")

    assert captured.value is failure
