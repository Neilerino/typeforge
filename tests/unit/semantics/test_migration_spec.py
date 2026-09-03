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
    CaptureValuePattern,
    CaseExpression,
    DeferredMap,
    DropExpression,
    DroppedField,
    EqualExpression,
    EvaluationContext,
    ExactTypePattern,
    ExpectedConditionSemanticError,
    ExpectedFieldNameSemanticError,
    ExpectedFieldSemanticError,
    ExpectedRecordSemanticError,
    ExpectedTypeSemanticError,
    Expression,
    FieldExpression,
    FieldName,
    IndeterminateCondition,
    InputReference,
    KeyReference,
    MapExpression,
    MapFieldsExpression,
    NotExpression,
    OptionalFieldExpression,
    ParameterizedTypePattern,
    ParameterizedTypeShape,
    ParameterizedTypeTemplate,
    ReadonlyFieldExpression,
    RecordFamily,
    RecordField,
    RecordShape,
    ResolvedType,
    SemanticAdapterError,
    SemanticIssue,
    SemanticIssueCode,
    TypeReference,
    TypeSystem,
    UnboundInputSemanticError,
    UnboundKeySemanticError,
    UnboundValueSemanticError,
    UnionExpression,
    UnresolvedType,
    UnresolvedTypeReference,
    ValueReference,
    evaluate,
    type_ref,
)


class NameTypeSystem:
    def __init__(
        self,
        records: tuple[tuple[str, RecordShape[str]], ...] = (),
        parameterized_types: tuple[tuple[str, ParameterizedTypeShape[str]], ...] = (),
    ) -> None:
        self._records = dict(records)
        self._parameterized_types = dict(parameterized_types)

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

    def inspect(
        self, value: str
    ) -> Result[ParameterizedTypeShape[str] | None, SemanticIssue]:
        return Success(self._parameterized_types.get(value))

    def build(self, shape: ParameterizedTypeShape[str]) -> Result[str, SemanticIssue]:
        value = next(
            (
                value
                for value, candidate in self._parameterized_types.items()
                if candidate == shape
            ),
            None,
        )
        if value is not None:
            return Success(value)
        return Failure(SemanticAdapterError(f"cannot build {shape!r}"))


class PythonTypeSystem:
    def __init__(
        self,
        parameterized_types: tuple[
            tuple[object, ParameterizedTypeShape[object]], ...
        ] = (),
    ) -> None:
        self._parameterized_types = dict(parameterized_types)

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

    def inspect(
        self, value: object
    ) -> Result[ParameterizedTypeShape[object] | None, SemanticIssue]:
        return Success(self._parameterized_types.get(value))

    def build(
        self, shape: ParameterizedTypeShape[object]
    ) -> Result[object, SemanticIssue]:
        value = next(
            (
                value
                for value, candidate in self._parameterized_types.items()
                if candidate == shape
            ),
            None,
        )
        if value is not None:
            return Success(value)
        return Failure(SemanticAdapterError(f"cannot build {shape!r}"))


type AdapterOperation = Literal[
    "equal",
    "assignable",
    "union_members",
    "union",
    "record",
    "inspect",
    "build",
]


class FailureInjectionTypeSystemProxy[T]:
    def __init__(
        self,
        type_system: TypeSystem[T],
        operation: AdapterOperation,
        issue: SemanticIssue,
    ) -> None:
        self._type_system = type_system
        self._operation = operation
        self._issue = issue

    def equal(self, left: T, right: T) -> Result[bool, SemanticIssue]:
        if self._operation == "equal":
            return Failure(self._issue)
        return self._type_system.equal(left, right)

    def assignable(self, source: T, target: T) -> Result[bool, SemanticIssue]:
        if self._operation == "assignable":
            return Failure(self._issue)
        return self._type_system.assignable(source, target)

    def union_members(self, value: T) -> Result[tuple[T, ...], SemanticIssue]:
        if self._operation == "union_members":
            return Failure(self._issue)
        return self._type_system.union_members(value)

    def union(self, members: tuple[T, ...]) -> Result[T, SemanticIssue]:
        if self._operation == "union":
            return Failure(self._issue)
        return self._type_system.union(members)

    def record(self, value: T) -> Result[RecordShape[T], SemanticIssue]:
        if self._operation == "record":
            return Failure(self._issue)
        return self._type_system.record(value)

    def inspect(
        self, value: T
    ) -> Result[ParameterizedTypeShape[T] | None, SemanticIssue]:
        if self._operation == "inspect":
            return Failure(self._issue)
        return self._type_system.inspect(value)

    def build(self, shape: ParameterizedTypeShape[T]) -> Result[T, SemanticIssue]:
        if self._operation == "build":
            return Failure(self._issue)
        return self._type_system.build(shape)


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

    result = evaluate(
        expression,
        FailureInjectionTypeSystemProxy(NameTypeSystem(), operation, issue),
    )

    assert isinstance(result, Failure)
    assert result.failure() is issue


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


def test_leaf_and_bound_context_expressions_produce_evaluation_values() -> None:
    """Leaf expressions resolve without exposing recursive traversal."""
    type_system = NameTypeSystem()

    assert evaluate(FieldName("name"), type_system) == Success(FieldName("name"))
    assert evaluate(DropExpression(), type_system) == Success(DroppedField())
    assert evaluate(
        KeyReference(),
        type_system,
        EvaluationContext(key="name"),
    ) == Success(FieldName("name"))


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


def test_map_without_a_match_resolves_to_never() -> None:
    """An omitted Map default resolves through the adapter's empty union."""
    expression = MapExpression(
        TypeReference("bytes"),
        (CaseExpression(TypeReference("int"), TypeReference("str")),),
    )

    assert evaluate(expression, NameTypeSystem()) == Success(ResolvedType("Never"))


def test_parameterized_map_semantics_are_shared_by_type_system_adapters() -> None:
    """`Map[T, Case[list[Value], set[Value]], Default[T]]` is shared."""
    name_type_system = NameTypeSystem(
        parameterized_types=(
            ("list[int]", ParameterizedTypeShape("list", ("int",))),
            ("set[int]", ParameterizedTypeShape("set", ("int",))),
        )
    )
    python_type_system = PythonTypeSystem(
        parameterized_types=(
            (list[int], ParameterizedTypeShape[object](list, (int,))),
            (set[int], ParameterizedTypeShape[object](set, (int,))),
        )
    )
    name_expression = MapExpression(
        TypeReference("list[int]"),
        (
            CaseExpression(
                ParameterizedTypePattern("list", (CaptureValuePattern(),)),
                ParameterizedTypeTemplate("set", (ValueReference(),)),
            ),
        ),
        TypeReference("list[int]"),
    )
    runtime_expression = MapExpression(
        type_ref(list[int]),
        (
            CaseExpression(
                ParameterizedTypePattern(list, (CaptureValuePattern(),)),
                ParameterizedTypeTemplate(set, (ValueReference(),)),
            ),
        ),
        type_ref(list[int]),
    )

    assert evaluate(name_expression, name_type_system) == Success(
        ResolvedType("set[int]")
    )
    assert evaluate(runtime_expression, python_type_system) == Success(
        ResolvedType(set[int])
    )


def test_parameterized_pattern_matches_nested_exact_and_capture_arguments() -> None:
    """`Case[dict[str, list[Value]], set[Value]]` captures the nested type."""
    type_system = NameTypeSystem(
        parameterized_types=(
            (
                "dict[str, list[int]]",
                ParameterizedTypeShape("dict", ("str", "list[int]")),
            ),
            ("list[int]", ParameterizedTypeShape("list", ("int",))),
            ("set[int]", ParameterizedTypeShape("set", ("int",))),
        )
    )
    expression = MapExpression(
        TypeReference("dict[str, list[int]]"),
        (
            CaseExpression(
                ParameterizedTypePattern(
                    "dict",
                    (
                        ExactTypePattern("str"),
                        ParameterizedTypePattern(
                            "list",
                            (CaptureValuePattern(),),
                        ),
                    ),
                ),
                ParameterizedTypeTemplate("set", (ValueReference(),)),
            ),
        ),
    )

    assert evaluate(expression, type_system) == Success(ResolvedType("set[int]"))


@pytest.mark.parametrize("subject", ("set[int]", "tuple[int, str]", "int"))
def test_parameterized_pattern_requires_matching_origin_and_arity(
    subject: str,
) -> None:
    """A different origin, arity, or plain type selects the `Map` default."""
    type_system = NameTypeSystem(
        parameterized_types=(
            ("set[int]", ParameterizedTypeShape("set", ("int",))),
            (
                "tuple[int, str]",
                ParameterizedTypeShape("tuple", ("int", "str")),
            ),
        )
    )
    expression = MapExpression(
        TypeReference(subject),
        (
            CaseExpression(
                ParameterizedTypePattern("tuple", (CaptureValuePattern(),)),
                TypeReference("matched"),
            ),
        ),
        TypeReference("not-matched"),
    )

    assert evaluate(expression, type_system) == Success(ResolvedType("not-matched"))


@pytest.mark.parametrize(
    ("subject", "expected"),
    (
        ("tuple[int, int]", "matched"),
        ("tuple[int, str]", "not-matched"),
    ),
)
def test_repeated_value_in_a_parameterized_pattern_is_one_capture(
    subject: str,
    expected: str,
) -> None:
    """Repeated `Value` positions must match the same captured type."""
    type_system = NameTypeSystem(
        parameterized_types=(
            (
                "tuple[int, int]",
                ParameterizedTypeShape("tuple", ("int", "int")),
            ),
            (
                "tuple[int, str]",
                ParameterizedTypeShape("tuple", ("int", "str")),
            ),
        )
    )
    expression = MapExpression(
        TypeReference(subject),
        (
            CaseExpression(
                ParameterizedTypePattern(
                    "tuple",
                    (CaptureValuePattern(), CaptureValuePattern()),
                ),
                TypeReference("matched"),
            ),
        ),
        TypeReference("not-matched"),
    )

    assert evaluate(expression, type_system) == Success(ResolvedType(expected))


@pytest.mark.parametrize(
    "operation",
    ("equal", "inspect", "build"),
)
def test_parameterized_type_adapter_failures_propagate_unchanged(
    operation: AdapterOperation,
) -> None:
    """Structural evaluation preserves the adapter's modeled failure."""
    issue = SemanticAdapterError(f"{operation} is unavailable")
    type_system = NameTypeSystem(
        parameterized_types=(
            ("list[int]", ParameterizedTypeShape("list", ("int",))),
            ("set[int]", ParameterizedTypeShape("set", ("int",))),
        )
    )
    expression = MapExpression(
        TypeReference("list[int]"),
        (
            CaseExpression(
                ParameterizedTypePattern("list", (CaptureValuePattern(),)),
                ParameterizedTypeTemplate("set", (ValueReference(),)),
            ),
        ),
    )

    result = evaluate(
        expression,
        FailureInjectionTypeSystemProxy(type_system, operation, issue),
    )

    assert isinstance(result, Failure)
    assert result.failure() is issue


def test_input_map_preserves_deferred_meaning_and_possible_output_type() -> None:
    """`Map[Input, Case[int, int], Case[str, UUID], Default[bytes]]` defers."""
    cases = (
        CaseExpression(TypeReference("int"), TypeReference("int")),
        CaseExpression(TypeReference("str"), TypeReference("UUID")),
    )
    default = TypeReference("bytes")
    expression = MapExpression(InputReference(), cases, default)

    assert evaluate(expression, NameTypeSystem()) == Success(
        DeferredMap(
            cases=cases,
            default=default,
            context=EvaluationContext(),
            possible_output=ResolvedType("int | UUID | bytes"),
        )
    )


def test_deferred_map_no_match_is_not_part_of_its_possible_output_type() -> None:
    """A deferred `Map` without `Default` can fail but cannot output `Never`."""
    cases = (
        CaseExpression(TypeReference("int"), TypeReference("int")),
        CaseExpression(TypeReference("str"), TypeReference("UUID")),
    )
    expression = MapExpression(InputReference(), cases)

    assert evaluate(expression, NameTypeSystem()) == Success(
        DeferredMap(
            cases=cases,
            default=None,
            context=EvaluationContext(),
            possible_output=ResolvedType("int | UUID"),
        )
    )


def test_deferred_map_normalizes_duplicate_possible_outputs() -> None:
    """Possible output types use the adapter's union normalization."""
    cases = (
        CaseExpression(TypeReference("int"), TypeReference("str")),
        CaseExpression(TypeReference("bytes"), TypeReference("str")),
    )
    default = TypeReference("bytes")
    expression = MapExpression(InputReference(), cases, default)

    result = evaluate(expression, NameTypeSystem())

    assert result == Success(
        DeferredMap(
            cases=cases,
            default=default,
            context=EvaluationContext(),
            possible_output=ResolvedType("str | bytes"),
        )
    )


def test_deferred_map_preserves_union_adapter_failures() -> None:
    """Possible output construction preserves the adapter's modeled failure."""
    issue = SemanticAdapterError("union is unavailable")
    expression = MapExpression(
        InputReference(),
        (CaseExpression(TypeReference("int"), TypeReference("str")),),
    )

    result = evaluate(
        expression,
        FailureInjectionTypeSystemProxy(NameTypeSystem(), "union", issue),
    )

    assert isinstance(result, Failure)
    assert result.failure() is issue


def test_deferred_map_preserves_and_uses_its_evaluation_context() -> None:
    """A deferred output can use a `MapFields` value binding available now."""
    context = EvaluationContext(value=ResolvedType("int"))
    cases = (CaseExpression(TypeReference("str"), ValueReference()),)
    expression = MapExpression(InputReference(), cases)

    result = evaluate(expression, NameTypeSystem(), context)

    assert result == Success(
        DeferredMap(
            cases=cases,
            default=None,
            context=context,
            possible_output=ResolvedType("int"),
        )
    )


def test_deferred_map_rejects_an_output_that_needs_future_input() -> None:
    """Possible outputs must resolve before the deferred input is available."""
    expression = MapExpression(
        InputReference(),
        (CaseExpression(TypeReference("int"), InputReference()),),
    )

    assert evaluate(expression, NameTypeSystem()) == Failure(
        UnboundInputSemanticError("Input requires value-time evaluation")
    )


def test_deferred_map_rejects_a_non_type_output() -> None:
    """Every possible deferred output must resolve to a type."""
    expression = MapExpression(
        InputReference(),
        (CaseExpression(TypeReference("int"), FieldName("not-a-type")),),
    )

    assert evaluate(expression, NameTypeSystem()) == Failure(
        ExpectedTypeSemanticError("deferred Map outputs must evaluate to types")
    )


def test_bound_input_evaluates_the_map_instead_of_deferring_it() -> None:
    """A bound `Input` selects an ordinary ordered `Map` output."""
    expression = MapExpression(
        InputReference(),
        (CaseExpression(TypeReference("int"), TypeReference("str")),),
        TypeReference("bytes"),
    )

    result = evaluate(
        expression,
        NameTypeSystem(),
        EvaluationContext(input_type=ResolvedType("int")),
    )

    assert result == Success(ResolvedType("str"))


def test_indeterminate_conditions_preserve_first_match_order() -> None:
    unresolved = UnresolvedTypeReference("T")
    unknown_case = CaseExpression(
        EqualExpression(unresolved, TypeReference("int")),
        TypeReference("str"),
    )

    assert evaluate(
        MapExpression(
            TypeReference("int"),
            (
                CaseExpression(TypeReference("int"), TypeReference("float")),
                unknown_case,
            ),
            TypeReference("bytes"),
        ),
        NameTypeSystem(),
    ) == Success(ResolvedType("float"))
    assert evaluate(
        MapExpression(
            TypeReference("int"),
            (
                CaseExpression(
                    EqualExpression(TypeReference("int"), TypeReference("str")),
                    TypeReference("float"),
                ),
                unknown_case,
            ),
            TypeReference("bytes"),
        ),
        NameTypeSystem(),
    ) == Success(UnresolvedType("str | bytes"))
    assert evaluate(
        EqualExpression(unresolved, TypeReference("int")),
        NameTypeSystem(),
    ) == Success(IndeterminateCondition())


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


def test_assignability_uses_the_type_system_adapter() -> None:
    """Assignable delegates backend-specific type relations to its adapter."""
    expression = AssignableExpression(
        TypeReference("int"),
        TypeReference("object"),
    )

    assert evaluate(expression, NameTypeSystem()) == Success(True)


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
