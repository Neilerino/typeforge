import pytest

from pydantic import TypeAdapter, ValidationError
from typeforge import Capture, Map
from typeforge.pydantic import Schema

Item = Capture("Item")


def test_structural_map_captures_and_substitutes_value() -> None:
    type Converted = Schema[
        Map[
            list[int],
            list[Item] : tuple[Item, ...],
            ...:bytes,
        ]
    ]
    adapter = TypeAdapter(Converted)

    assert adapter.validate_python(["1", 2]) == (1, 2)


def test_structural_map_substitutes_multiple_output_positions() -> None:
    type Converted = Schema[
        Map[
            list[int],
            list[Item] : dict[str, Item],
            ...:bytes,
        ]
    ]
    adapter = TypeAdapter(Converted)

    assert adapter.validate_python({"one": "1", "two": 2}) == {
        "one": 1,
        "two": 2,
    }


def test_structural_map_uses_default_for_different_constructor() -> None:
    type Converted = Schema[
        Map[
            set[int],
            list[Item] : tuple[Item, ...],
            ...:bytes,
        ]
    ]
    adapter = TypeAdapter(Converted)

    assert adapter.validate_python("value") == b"value"
    with pytest.raises(ValidationError):
        adapter.validate_python([1, 2])


def test_structural_capture_can_drive_a_nested_map() -> None:
    type Converted = Schema[
        Map[
            list[int],
            list[Item] : Map[Item, int:str, ...:bytes],
            ...:float,
        ]
    ]
    adapter = TypeAdapter(Converted)

    assert adapter.validate_python("captured") == "captured"
