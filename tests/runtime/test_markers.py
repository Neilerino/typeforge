from typing import get_args

from typeforge import (
    All,
    Any,
    Assignable,
    Case,
    Collect,
    Default,
    Drop,
    Each,
    Equal,
    Field,
    If,
    Key,
    Map,
    MapFields,
    Not,
    OptionalField,
    ReadonlyField,
    Value,
)


def test_variadic_markers_preserve_arguments() -> None:
    assert get_args(Each[int]) == (int,)
    assert get_args(Collect[int]) == (int,)


def test_condition_markers_preserve_arguments() -> None:
    assert get_args(If[Assignable[int, object], str, bytes]) == (
        Assignable[int, object],
        str,
        bytes,
    )
    assert get_args(Equal[int, str]) == (int, str)
    assert get_args(All[Equal[int, int], Assignable[int, object]]) == (
        Equal[int, int],
        Assignable[int, object],
    )
    assert get_args(Any[Equal[int, str], Equal[int, int]]) == (
        Equal[int, str],
        Equal[int, int],
    )
    assert get_args(Not[Equal[int, str]]) == (Equal[int, str],)


def test_map_markers_preserve_arguments() -> None:
    mapping = Map[int, Case[int, str], Default[bytes]]
    assert get_args(mapping) == (int, Case[int, str], Default[bytes])


def test_field_markers_preserve_arguments() -> None:
    assert get_args(MapFields[dict[str, int], Field[Key, Value]]) == (
        dict[str, int],
        Field[Key, Value],
    )
    assert get_args(OptionalField[Key, Value]) == (Key, Value)
    assert get_args(ReadonlyField[Key, Value]) == (Key, Value)
    assert repr(Drop) == "Drop"
