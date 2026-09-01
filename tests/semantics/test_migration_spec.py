"""Migration is complete when every strict xfail marker can be removed."""

from datetime import datetime
from pathlib import Path
from typing import Literal, Never

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
    EvaluationContext,
    ExpectedConditionSemanticError,
    ExpectedFieldNameSemanticError,
    ExpectedFieldSemanticError,
    ExpectedRecordSemanticError,
    ExpectedTypeSemanticError,
    Expression,
    FieldExpression,
    FieldName,
    InputReference,
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
    SemanticAdapterError,
    SemanticIssue,
    SemanticIssueCode,
    TypeReference,
    UnboundInputSemanticError,
    UnboundKeySemanticError,
    UnboundValueSemanticError,
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

    def union_members(self, value: str) -> Result[tuple[str, ...], SemanticIssue]:
        if value == "Never":
            return Success(())
        return Success(tuple(value.split(" | ")))

    def union(self, members: tuple[str, ...]) -> Result[str, SemanticIssue]:
        return Success(" | ".join(dict.fromkeys(members)) or "Never")

    def record(self, value: str) -> Result[RecordShape[str], SemanticIssue]:
        shape = self._records.get(value)
        if shape is not None:
            return Success(shape)
        return Failure(
            ExpectedRecordSemanticError(f"{value} is not a supported record")
        )


class PythonTypeSystem:
    def equal(self, left: object, right: object) -> Result[bool, SemanticIssue]:
        return Success(left == right)

    def assignable(self, source: object, target: object) -> Result[bool, SemanticIssue]:
        if isinstance(source, type) and isinstance(target, type):
            return Success(issubclass(source, target))
        return Success(source == target)

    def union_members(self, value: object) -> Result[tuple[object, ...], SemanticIssue]:
        if value is Never:
            return Success(())
        if isinstance(value, tuple):
            return Success(value)
        return Success((value,))

    def union(self, members: tuple[object, ...]) -> Result[object, SemanticIssue]:
        unique_members = tuple(dict.fromkeys(members))
        if not unique_members:
            return Success(Never)
        if len(unique_members) == 1:
            return Success(unique_members[0])
        return Success(unique_members)

    def record(self, value: object) -> Result[RecordShape[object], SemanticIssue]:
        return Failure(
            ExpectedRecordSemanticError(f"{value!r} is not a supported record")
        )


type AdapterOperation = Literal[
    "equal",
    "assignable",
    "union_members",
    "union",
    "record",
]


class FailingNameTypeSystem(NameTypeSystem):
    def __init__(
        self,
        operation: AdapterOperation,
        issue: SemanticIssue,
    ) -> None:
        super().__init__()
        self._operation = operation
        self._issue = issue

    def equal(self, left: str, right: str) -> Result[bool, SemanticIssue]:
        if self._operation == "equal":
            return Failure(self._issue)
        return super().equal(left, right)

    def assignable(self, source: str, target: str) -> Result[bool, SemanticIssue]:
        if self._operation == "assignable":
            return Failure(self._issue)
        return super().assignable(source, target)

    def union_members(self, value: str) -> Result[tuple[str, ...], SemanticIssue]:
        if self._operation == "union_members":
            return Failure(self._issue)
        return super().union_members(value)

    def union(self, members: tuple[str, ...]) -> Result[str, SemanticIssue]:
        if self._operation == "union":
            return Failure(self._issue)
        return super().union(members)

    def record(self, value: str) -> Result[RecordShape[str], SemanticIssue]:
        if self._operation == "record":
            return Failure(self._issue)
        return super().record(value)


@MIGRATION_INCOMPLETE
@pytest.mark.parametrize(
    ("operation", "expression"),
    (
        (
            "equal",
            EqualExpression(TypeReference("int"), TypeReference("str")),
        ),
        (
            "assignable",
            AssignableExpression(TypeReference("int"), TypeReference("object")),
        ),
        (
            "union_members",
            MapExpression(
                TypeReference("int"),
                (CaseExpression(TypeReference("int"), TypeReference("str")),),
            ),
        ),
        (
            "union",
            UnionExpression((TypeReference("int"), TypeReference("str"))),
        ),
        (
            "record",
            MapFieldsExpression(
                TypeReference("Payload"),
                FieldExpression(KeyReference(), ValueReference()),
            ),
        ),
    ),
)
def test_adapter_failures_propagate_unchanged(
    operation: AdapterOperation,
    expression: Expression[str],
) -> None:
    """The semantic seam preserves a concrete adapter's modeled failure."""
    issue = SemanticAdapterError(f"{operation} is unavailable")

    result = evaluate(expression, FailingNameTypeSystem(operation, issue))

    assert isinstance(result, Failure)
    assert result.failure() is issue


@MIGRATION_INCOMPLETE
@pytest.mark.parametrize(
    ("expression", "issue"),
    (
        (
            KeyReference(),
            UnboundKeySemanticError("Key requires MapFields"),
        ),
        (
            ValueReference(),
            UnboundValueSemanticError(
                "Value requires MapFields or a structural Map case"
            ),
        ),
        (
            InputReference(),
            UnboundInputSemanticError("Input requires value-time evaluation"),
        ),
    ),
)
def test_unbound_context_references_return_specific_failures(
    expression: Expression[str],
    issue: SemanticIssue,
) -> None:
    """Contextual references fail with stable codes and authored vocabulary."""
    assert evaluate(expression, NameTypeSystem()) == Failure(issue)


@MIGRATION_INCOMPLETE
@pytest.mark.parametrize(
    ("expression", "issue"),
    (
        (
            EqualExpression(TypeReference("int"), FieldName("name")),
            ExpectedTypeSemanticError(
                "Equal operands must both be types or both be field names"
            ),
        ),
        (
            AssignableExpression(FieldName("name"), TypeReference("object")),
            ExpectedTypeSemanticError("Assignable operands must both be types"),
        ),
        (
            AllExpression((TypeReference("int"),)),
            ExpectedConditionSemanticError("condition must evaluate to bool"),
        ),
        (
            FieldExpression(TypeReference("int"), TypeReference("str")),
            ExpectedFieldNameSemanticError("field name must evaluate to FieldName"),
        ),
        (
            FieldExpression[str](FieldName("name"), FieldName("value")),
            ExpectedTypeSemanticError("field value must evaluate to a type"),
        ),
        (
            UnionExpression((TypeReference("int"), FieldName("name"))),
            ExpectedTypeSemanticError("union members must evaluate to types"),
        ),
    ),
)
def test_evaluation_roles_reject_incompatible_values(
    expression: Expression[str],
    issue: SemanticIssue,
) -> None:
    """Each expression accepts only the evaluation-value roles it declares."""
    assert evaluate(expression, NameTypeSystem()) == Failure(issue)


@MIGRATION_INCOMPLETE
def test_map_fields_rejects_a_non_field_transform_result() -> None:
    """MapFields accepts transformed fields or Drop, never a resolved type."""
    payload = RecordShape(
        RecordFamily.TYPED_DICT,
        "Payload",
        (RecordField("value", "int"),),
    )

    result = evaluate(
        MapFieldsExpression(
            TypeReference("Payload"),
            ValueReference(),
        ),
        NameTypeSystem((("Payload", payload),)),
    )

    assert result == Failure(
        ExpectedFieldSemanticError(
            "MapFields transform must evaluate to a field or Drop"
        )
    )


@MIGRATION_INCOMPLETE
@pytest.mark.parametrize(
    ("expression", "context"),
    (
        (
            ValueReference(),
            EvaluationContext[object](value=ResolvedType(None)),
        ),
        (
            InputReference(),
            EvaluationContext[object](input_type=ResolvedType(None)),
        ),
    ),
)
def test_none_is_a_bound_context_type(
    expression: Expression[object],
    context: EvaluationContext[object],
) -> None:
    """A resolved None is observable and does not take an unbound path."""
    assert evaluate(expression, PythonTypeSystem(), context) == Success(
        ResolvedType(None)
    )


@MIGRATION_INCOMPLETE
def test_map_distributes_native_union_members_from_the_adapter() -> None:
    """Union decomposition is native while ordered Map behavior stays shared."""
    expression = MapExpression(
        TypeReference("int | bytes | datetime"),
        (
            CaseExpression(TypeReference("int"), TypeReference("str")),
            CaseExpression(TypeReference("bytes"), TypeReference("str")),
        ),
        TypeReference("datetime"),
    )

    assert evaluate(expression, NameTypeSystem()) == Success(
        ResolvedType("str | datetime")
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
    transform = MapExpression[str](
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
    from typing import TypedDict

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
