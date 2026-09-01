"""Migration is complete when every strict xfail marker can be removed."""

from datetime import datetime
from pathlib import Path
from typing import Never

import pytest
from returns.result import Failure, Result, Success

from pydantic import TypeAdapter
from typeforge import Field as MarkerField
from typeforge import MapFields as MarkerMapFields
from typeforge import Value as MarkerValue
from typeforge.compiler.pipeline import generate_module
from typeforge.pydantic import Schema
from typeforge.semantics import (
    AllExpression,
    AnyExpression,
    AssignableExpression,
    CaseExpression,
    DropExpression,
    EqualExpression,
    FieldExpression,
    FieldName,
    KeyReference,
    MapExpression,
    MapFieldsExpression,
    NotExpression,
    OptionalFieldExpression,
    ReadonlyFieldExpression,
    RecordFamily,
    RecordField,
    RecordShape,
    ResolvedType,
    SemanticIssue,
    SemanticIssueCode,
    TypeReference,
    UnionExpression,
    ValueReference,
    evaluate,
    type_ref,
)

MIGRATION_INCOMPLETE = pytest.mark.xfail(
    strict=True,
    reason="shared semantic evaluator migration is incomplete",
)


class NameTypeSystem:
    def __init__(self, records: tuple[tuple[str, RecordShape[str]], ...] = ()) -> None:
        self._records = dict(records)

    def equal(self, left: str, right: str) -> Result[bool, SemanticIssue]:
        return Success(left == right)

    def assignable(self, source: str, target: str) -> Result[bool, SemanticIssue]:
        return Success(source == target or target == "object")

    def union(self, members: tuple[str, ...]) -> Result[str, SemanticIssue]:
        return Success(" | ".join(dict.fromkeys(members)) or "Never")

    def record(self, value: str) -> Result[RecordShape[str], SemanticIssue]:
        shape = self._records.get(value)
        if shape is not None:
            return Success(shape)
        return Failure(
            SemanticIssue(
                SemanticIssueCode.EXPECTED_RECORD,
                f"{value} is not a supported record",
            )
        )


class PythonTypeSystem:
    def equal(self, left: object, right: object) -> Result[bool, SemanticIssue]:
        return Success(left == right)

    def assignable(self, source: object, target: object) -> Result[bool, SemanticIssue]:
        if isinstance(source, type) and isinstance(target, type):
            return Success(issubclass(source, target))
        return Success(source == target)

    def union(self, members: tuple[object, ...]) -> Result[object, SemanticIssue]:
        unique_members = tuple(dict.fromkeys(members))
        if not unique_members:
            return Success(Never)
        if len(unique_members) == 1:
            return Success(unique_members[0])
        return Success(unique_members)

    def record(self, value: object) -> Result[RecordShape[object], SemanticIssue]:
        return Failure(
            SemanticIssue(
                SemanticIssueCode.EXPECTED_RECORD,
                f"{value!r} is not a supported record",
            )
        )


@MIGRATION_INCOMPLETE
def test_map_is_ordered_and_distributes_over_unions() -> None:
    """Map preserves first-match order and unions its resolved outputs."""
    expression = MapExpression(
        UnionExpression(
            (
                type_ref(int),
                type_ref(bytes),
                type_ref(datetime),
            )
        ),
        (
            CaseExpression(type_ref(int), type_ref(str)),
            CaseExpression(type_ref(int), type_ref(bytes)),
            CaseExpression(type_ref(bytes), type_ref(str)),
        ),
        type_ref(datetime),
    )

    assert evaluate(expression, PythonTypeSystem()) == Success(
        ResolvedType((str, datetime))
    )


@MIGRATION_INCOMPLETE
def test_map_without_a_match_resolves_to_never() -> None:
    """An omitted Map default resolves through the adapter's empty union."""
    expression = MapExpression(
        type_ref(bytes),
        (CaseExpression(type_ref(int), type_ref(str)),),
    )

    assert evaluate(expression, NameTypeSystem()) == Success(ResolvedType("Never"))


@MIGRATION_INCOMPLETE
def test_conditions_short_circuit_nested_failures() -> None:
    """All and Any stop before evaluating an unreachable failing operand."""
    all_expression = AllExpression(
        (
            EqualExpression(TypeReference("int"), TypeReference("str")),
            KeyReference(),
        )
    )
    any_expression = AnyExpression(
        (
            EqualExpression(TypeReference("int"), TypeReference("int")),
            KeyReference(),
        )
    )

    assert evaluate(all_expression, NameTypeSystem()) == Success(False)
    assert evaluate(any_expression, NameTypeSystem()) == Success(True)
    assert evaluate(NotExpression(all_expression), NameTypeSystem()) == Success(True)


@MIGRATION_INCOMPLETE
def test_assignability_uses_the_type_system_adapter() -> None:
    """Assignable delegates backend-specific type relations to its adapter."""
    expression = AssignableExpression(
        TypeReference("int"),
        TypeReference("object"),
    )

    assert evaluate(expression, NameTypeSystem()) == Success(True)


@MIGRATION_INCOMPLETE
def test_map_fields_preserves_family_and_field_modifiers() -> None:
    """MapFields keeps record family while transforming field semantics."""
    credentials = RecordShape(
        RecordFamily.TYPED_DICT,
        "Credentials",
        (
            RecordField("password", "str"),
            RecordField("token", "str"),
            RecordField("attempts", "int"),
        ),
    )
    transform = MapExpression(
        KeyReference(),
        (
            CaseExpression(
                EqualExpression(KeyReference(), FieldName("password")),
                DropExpression(),
            ),
            CaseExpression(
                EqualExpression(KeyReference(), FieldName("token")),
                ReadonlyFieldExpression(KeyReference(), ValueReference()),
            ),
        ),
        OptionalFieldExpression(KeyReference(), ValueReference()),
    )

    result = evaluate(
        MapFieldsExpression(
            TypeReference("Credentials"),
            transform,
            "PublicCredentials",
        ),
        NameTypeSystem((("Credentials", credentials),)),
    )

    assert result == Success(
        RecordShape(
            RecordFamily.TYPED_DICT,
            "PublicCredentials",
            (
                RecordField("token", "str", readonly=True),
                RecordField("attempts", "int", required=False),
            ),
        )
    )


@MIGRATION_INCOMPLETE
def test_map_fields_rejects_duplicate_output_names() -> None:
    """Every record adapter rejects duplicate transformed field names."""
    pair = RecordShape(
        RecordFamily.TYPED_DICT,
        "Pair",
        (
            RecordField("left", "int"),
            RecordField("right", "int"),
        ),
    )

    result = evaluate(
        MapFieldsExpression(
            TypeReference("Pair"),
            FieldExpression(FieldName("same"), ValueReference()),
        ),
        NameTypeSystem((("Pair", pair),)),
    )

    assert isinstance(result, Failure)
    assert result.failure().code is SemanticIssueCode.DUPLICATE_FIELD


@MIGRATION_INCOMPLETE
def test_two_type_system_adapters_share_map_semantics() -> None:
    """Compiler-like and runtime-like types resolve through the same seam."""
    name_expression = MapExpression(
        TypeReference("int"),
        (CaseExpression(TypeReference("int"), TypeReference("str")),),
        TypeReference("bytes"),
    )
    runtime_expression = MapExpression(
        type_ref(int),
        (CaseExpression(type_ref(int), type_ref(str)),),
        type_ref(bytes),
    )

    assert evaluate(name_expression, NameTypeSystem()) == Success(ResolvedType("str"))
    assert evaluate(runtime_expression, PythonTypeSystem()) == Success(
        ResolvedType(str)
    )


@MIGRATION_INCOMPLETE
def test_compiler_and_runtime_reject_duplicate_record_outputs(
    tmp_path: Path,
) -> None:
    """Static and runtime record adapters enforce the same invariants."""
    from typing import Literal, TypedDict

    class Pair(TypedDict):
        left: int
        right: int

    type Duplicate[T] = MarkerMapFields[
        T,
        MarkerField[Literal["same"], MarkerValue],
    ]

    with pytest.raises(Exception, match=r"duplicate_field.*'same'"):
        TypeAdapter(Schema[Duplicate[Pair]])

    source = tmp_path / "duplicate_record.py"
    source.write_text(
        """
from typing import Literal, TypedDict
from typeforge import Field, MapFields, Value

class Pair(TypedDict):
    left: int
    right: int

type Duplicate[T] = MapFields[T, Field[Literal["same"], Value]]

def duplicate(value: Pair) -> Duplicate[Pair]: ...
""".lstrip(),
        encoding="utf-8",
    )

    generated = generate_module(source, maximum_arity=2)

    assert isinstance(generated, Failure)
    assert "multiple source fields produce 'same'" in generated.failure().message
