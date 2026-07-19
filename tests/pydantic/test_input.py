from uuid import UUID

import pytest

from pydantic import TypeAdapter, ValidationError
from typeforge import Case, Default, Equal, If, Map
from typeforge.pydantic import Input, Schema


def test_input_map_dispatches_on_raw_exact_type() -> None:
    type Identifier = Schema[
        Map[
            Input,
            Case[int, int],
            Case[str, UUID],
        ]
    ]
    adapter = TypeAdapter(Identifier)
    identifier = UUID("12345678-1234-5678-1234-567812345678")

    assert adapter.validate_python(3) == 3
    assert adapter.validate_python(str(identifier)) == identifier
    with pytest.raises(ValidationError):
        adapter.validate_python(True)
    with pytest.raises(ValidationError):
        adapter.validate_python(3.0)


def test_input_map_supports_json_and_default() -> None:
    type Value = Schema[
        Map[
            Input,
            Case[int, int],
            Default[str],
        ]
    ]
    adapter = TypeAdapter(Value)

    assert adapter.validate_json("3") == 3
    assert adapter.validate_json('"hello"') == "hello"


def test_input_map_serializes_selected_output() -> None:
    type Identifier = Schema[
        Map[
            Input,
            Case[int, int],
            Case[str, UUID],
        ]
    ]
    adapter = TypeAdapter(Identifier)
    identifier = UUID("12345678-1234-5678-1234-567812345678")

    value = adapter.validate_python(str(identifier))

    assert adapter.dump_json(value) == b'"12345678-1234-5678-1234-567812345678"'


def test_input_if_dispatches() -> None:
    type Identifier = Schema[If[Equal[Input, str], UUID, int]]
    adapter = TypeAdapter(Identifier)
    identifier = UUID("12345678-1234-5678-1234-567812345678")

    assert adapter.validate_python(str(identifier)) == identifier
    assert adapter.validate_python(3) == 3


def test_input_map_selects_from_raw_input_when_outputs_overlap_inputs() -> None:
    type Swapped = Schema[
        Map[
            Input,
            Case[str, int],
            Case[int, float],
        ]
    ]
    adapter = TypeAdapter(Swapped)

    assert adapter.validate_python("3") == 3
    mapped = adapter.validate_python(3)
    assert mapped == 3.0
    assert type(mapped) is float
    assert adapter.dump_python(3) == 3
    assert adapter.dump_python(3.0) == 3.0


def test_input_if_selects_from_condition_when_outputs_overlap_inputs() -> None:
    type Swapped = Schema[If[Equal[Input, str], int, float]]
    adapter = TypeAdapter(Swapped)

    assert adapter.validate_python("3") == 3
    mapped = adapter.validate_python(3)
    assert mapped == 3.0
    assert type(mapped) is float


def test_input_dispatch_json_schema_is_honest_about_validation_input() -> None:
    type Swapped = Schema[Map[Input, Case[str, int], Case[int, float]]]
    adapter = TypeAdapter(Swapped)

    assert adapter.json_schema(mode="validation") == {}
    assert adapter.json_schema(mode="serialization") == {}
