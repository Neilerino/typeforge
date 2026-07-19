import pytest

from pydantic import TypeAdapter
from typeforge import All, Any, Case, Each, Equal, Field, If, Key, Map, MapFields, Value
from typeforge.pydantic import Input, Schema


def test_unbound_field_placeholders_fail_during_schema_generation() -> None:
    with pytest.raises(Exception, match=r"unbound_key.*Key is only valid"):
        TypeAdapter(Schema[Key])
    with pytest.raises(Exception, match=r"unbound_value.*Value requires"):
        TypeAdapter(Schema[Value])


def test_nested_schema_failure_preserves_the_original_issue() -> None:
    with pytest.raises(Exception, match=r"unbound_key.*Key is only valid"):
        TypeAdapter(Schema[If[Equal[Key, Key], int, str]])


def test_schema_conditions_short_circuit_nested_failures() -> None:
    all_adapter = TypeAdapter(
        Schema[If[All[Equal[int, str], Equal[Key, Key]], bytes, int]]
    )
    any_adapter = TypeAdapter(
        Schema[If[Any[Equal[int, int], Equal[Key, Key]], int, bytes]]
    )

    assert all_adapter.validate_python("3") == 3
    assert any_adapter.validate_python("3") == 3


def test_malformed_map_reports_operator_and_phase() -> None:
    with pytest.raises(Exception, match=r"evaluation.*invalid_marker.*Map entries"):
        TypeAdapter(Schema[Map[int, str]])


def test_callable_only_relationship_is_rejected() -> None:
    with pytest.raises(
        Exception,
        match=r"unsupported_relationship.*no Pydantic model-field semantics",
    ):
        TypeAdapter(Schema[Each[int]])


def test_map_fields_transform_must_produce_a_field_or_drop() -> None:
    from typing import TypedDict

    class Payload(TypedDict):
        value: int

    with pytest.raises(Exception, match=r"expected_field.*must produce Field"):
        TypeAdapter(Schema[MapFields[Payload, Value]])


def test_map_fields_rejects_duplicate_renames() -> None:
    from typing import Literal, TypedDict

    class Payload(TypedDict):
        left: int
        right: int

    with pytest.raises(Exception, match=r"duplicate_field.*'same'"):
        TypeAdapter(Schema[MapFields[Payload, Field[Literal["same"], Value]]])


def test_value_time_map_rejects_undefined_generic_patterns() -> None:
    with pytest.raises(
        Exception,
        match=r"planning.*value-time generic Map patterns are not supported",
    ):
        TypeAdapter(Schema[Map[Input, Case[list[int], str]]])


def test_recursive_typeforge_alias_fails_instead_of_delegating_inert_markers() -> None:
    from typeforge import Equal, If

    type Recursive = If[Equal[int, int], int | list[Recursive], bytes]

    with pytest.raises(Exception, match=r"alias_cycle.*recursive aliases"):
        TypeAdapter(Schema[Recursive])
