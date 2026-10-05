import pytest
from returns.result import Failure, Success

from typeforge.compiler.semantic_adapter import (
    COMPILER_TYPE_SYSTEM,
    NEVER,
    NamedType,
    ParameterizedType,
    StaticType,
    UnionType,
)
from typeforge.semantics import (
    AssignableExpression,
    CaseExpression,
    FieldExpression,
    FieldNameReference,
    FieldTypeReference,
    MapExpression,
    MapNoMatch,
    ParameterizedTypeShape,
    RecordExpression,
    RecordFamily,
    RecordField,
    RecordShape,
    ResolvedType,
    SemanticIssueCode,
    TypeReference,
    TypeSymbol,
    evaluate,
)

FIELD = TypeSymbol(("test-field",), "field")

INT: StaticType = NamedType("int", ("object",))
STR: StaticType = NamedType("str", ("object",))
BYTES: StaticType = NamedType("bytes", ("object",))
OBJECT: StaticType = NamedType("object")
DATETIME: StaticType = NamedType("datetime", ("object",))


def type_reference(value: StaticType) -> TypeReference[StaticType]:
    return TypeReference(value=value)


def test_compiler_type_system_inspects_parameterized_types() -> None:
    value = ParameterizedType(NamedType("list"), (INT,))

    assert COMPILER_TYPE_SYSTEM.inspect(value) == Success(
        ParameterizedTypeShape(NamedType("list"), (INT,))
    )


def test_compiler_type_system_builds_parameterized_types() -> None:
    shape = ParameterizedTypeShape[StaticType](NamedType("set"), (INT,))

    assert COMPILER_TYPE_SYSTEM.build(shape) == Success(
        ParameterizedType(NamedType("set"), (INT,))
    )


def test_assignable_understands_union_sources_and_targets() -> None:
    assert evaluate(
        AssignableExpression(
            source=type_reference(UnionType(INT, STR)),
            target=type_reference(OBJECT),
        ),
        COMPILER_TYPE_SYSTEM,
    ) == Success(True)

    assert evaluate(
        AssignableExpression(
            source=type_reference(INT),
            target=type_reference(UnionType(STR, OBJECT)),
        ),
        COMPILER_TYPE_SYSTEM,
    ) == Success(True)

    assert evaluate(
        AssignableExpression(
            source=type_reference(UnionType(INT, STR)),
            target=type_reference(INT),
        ),
        COMPILER_TYPE_SYSTEM,
    ) == Success(False)


def test_map_matches_exact_types_and_uses_default() -> None:
    expression = MapExpression(
        subject=type_reference(UnionType(INT, BYTES, DATETIME)),
        cases=(
            CaseExpression(
                test=type_reference(INT),
                output=type_reference(STR),
            ),
            CaseExpression(
                test=type_reference(BYTES),
                output=type_reference(STR),
            ),
        ),
        default=type_reference(DATETIME),
    )

    assert evaluate(expression, COMPILER_TYPE_SYSTEM) == Success(
        ResolvedType(value=UnionType(STR, DATETIME))
    )


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    (
        (NEVER, UnionType(), True),
        (INT, UnionType(), False),
        (UnionType(), INT, True),
        (UnionType(INT, UnionType(STR, NEVER)), UnionType(STR, OBJECT), True),
        (UnionType(INT, UnionType(STR, BYTES)), UnionType(INT, STR), False),
    ),
)
def test_assignability_preserves_empty_and_nested_union_semantics(
    source: StaticType, target: StaticType, expected: bool
) -> None:
    assert COMPILER_TYPE_SYSTEM.assignable(source, target) == Success(expected)


def test_parameterized_types_follow_the_schema_object_supertype_rule() -> None:
    """The shared adapter retains Schema's existing list[int] -> object rule."""
    value = ParameterizedType(NamedType("list"), (INT,))

    assert COMPILER_TYPE_SYSTEM.assignable(value, OBJECT) == Success(True)


def test_map_rejects_a_known_uncovered_subject() -> None:
    expression = MapExpression(
        subject=type_reference(BYTES),
        cases=(
            CaseExpression(
                test=type_reference(INT),
                output=type_reference(STR),
            ),
        ),
    )

    result = evaluate(expression, COMPILER_TYPE_SYSTEM)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), MapNoMatch)
    assert result.failure().subject == ResolvedType(BYTES)


def test_map_fields_rejects_non_record_input() -> None:
    result = evaluate(
        RecordExpression(
            record=type_reference(INT),
            binding=FIELD,
            transform=FieldExpression(
                name=FieldNameReference(FIELD), value=FieldTypeReference(FIELD)
            ),
        ),
        COMPILER_TYPE_SYSTEM,
    )

    assert isinstance(result, Failure)
    assert result.failure().code is SemanticIssueCode.EXPECTED_RECORD


def test_record_shapes_are_used_without_translation() -> None:
    source: StaticType = RecordShape[StaticType](
        family=RecordFamily.TYPED_DICT,
        name="Payload",
        fields=(
            RecordField[StaticType](
                name="value",
                value=INT,
                required=False,
                readonly=True,
            ),
        ),
    )

    assert COMPILER_TYPE_SYSTEM.record(source) == Success(source)
