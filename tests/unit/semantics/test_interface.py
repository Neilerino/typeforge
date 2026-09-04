from dataclasses import FrozenInstanceError
from typing import assert_type

import pytest
from returns.result import Result, Success

from typeforge.semantics import (
    EvaluationContext,
    ParameterizedTypeShape,
    RecordFamily,
    RecordField,
    RecordShape,
    ResolvedType,
    SemanticIssue,
    TypeReference,
    TypeSystem,
    evaluate,
    type_ref,
)


class NameTypeSystem:
    def equal(self, left: str, right: str) -> Result[bool, SemanticIssue]:
        return Success(left == right)

    def assignable(self, source: str, target: str) -> Result[bool, SemanticIssue]:
        return Success(source == target or target == "object")

    def union_members(self, value: str) -> Result[tuple[str, ...], SemanticIssue]:
        if value == "Never":
            return Success(())

        return Success(tuple(value.split(" | ")))

    def union(self, members: tuple[str, ...]) -> Result[str, SemanticIssue]:
        return Success(" | ".join(dict.fromkeys(members)) or "Never")

    def record(self, value: str) -> Result[RecordShape[str], SemanticIssue]:
        return Success(RecordShape(RecordFamily.TYPED_DICT, value, ()))

    def inspect(
        self, value: str
    ) -> Result[ParameterizedTypeShape[str] | None, SemanticIssue]:
        raise NotImplementedError

    def build(self, shape: ParameterizedTypeShape[str]) -> Result[str, SemanticIssue]:
        raise NotImplementedError


def test_record_data_is_family_aware_and_immutable() -> None:
    """Record adapters share immutable data without losing record family."""
    field = RecordField("value", "int", required=False, readonly=True)
    shape = RecordShape(RecordFamily.TYPED_DICT, "Payload", (field,))

    assert shape == RecordShape(RecordFamily.TYPED_DICT, "Payload", (field,))
    with pytest.raises(FrozenInstanceError):
        field.name = "changed"  # type: ignore - testing


def test_type_system_is_the_supported_adapter_seam() -> None:
    """Compiler and runtime adapters satisfy one structural interface."""
    adapter = NameTypeSystem()

    assert isinstance(adapter, TypeSystem)


def test_evaluate_is_the_single_semantic_interface() -> None:
    """Semantic expressions resolve through one backend-neutral interface."""
    result = evaluate(
        TypeReference("int"),
        NameTypeSystem(),
        EvaluationContext(),
    )

    assert result == Success(ResolvedType("int"))


def test_evaluation_context_distinguishes_none_from_an_unbound_type() -> None:
    """Runtime adapters can bind None without using it as the unbound sentinel."""
    context = EvaluationContext[object](
        value=ResolvedType(None),
        capture=ResolvedType(None),
        input_type=ResolvedType(None),
    )

    assert_type(context.value, ResolvedType[object] | None)
    assert context.value == ResolvedType(None)
    assert context.capture == ResolvedType(None)
    assert context.input_type == ResolvedType(None)


def test_type_ref_constructs_a_runtime_domain_reference() -> None:
    """Runtime type references widen to the adapter's shared object domain."""
    reference = type_ref(int)

    assert_type(reference, TypeReference[object])
    assert reference == TypeReference(int)
