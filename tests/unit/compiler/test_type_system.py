from returns.result import Failure, Success

from typeforge.compiler._type_system import (
    COMPILER_TYPE_SYSTEM,
    typed_dict_shape,
)
from typeforge.compiler.records import (
    NEVER,
    NamedType,
    StaticType,
    TypedDictField,
    TypedDictShape,
    UnionType,
)
from typeforge.semantics import (
    AssignableExpression,
    CaseExpression,
    FieldExpression,
    KeyReference,
    MapExpression,
    MapFieldsExpression,
    ResolvedType,
    SemanticIssueCode,
    TypeReference,
    ValueReference,
    evaluate,
)

INT: StaticType = NamedType("int", ("object",))
STR: StaticType = NamedType("str", ("object",))
BYTES: StaticType = NamedType("bytes", ("object",))
OBJECT: StaticType = NamedType("object")
DATETIME: StaticType = NamedType("datetime", ("object",))


def type_reference(value: StaticType) -> TypeReference[StaticType]:
    return TypeReference(value=value)


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


def test_map_defaults_to_never() -> None:
    expression = MapExpression(
        subject=type_reference(BYTES),
        cases=(
            CaseExpression(
                test=type_reference(INT),
                output=type_reference(STR),
            ),
        ),
    )

    assert evaluate(expression, COMPILER_TYPE_SYSTEM) == Success(
        ResolvedType(value=NEVER)
    )


def test_map_fields_rejects_non_record_input() -> None:
    result = evaluate(
        MapFieldsExpression(
            record=type_reference(INT),
            transform=FieldExpression(
                name=KeyReference(),
                value=ValueReference(),
            ),
        ),
        COMPILER_TYPE_SYSTEM,
    )

    assert isinstance(result, Failure)
    assert result.failure().code is SemanticIssueCode.EXPECTED_RECORD


def test_typed_dict_shapes_round_trip_through_the_semantic_record_model() -> None:
    source: StaticType = TypedDictShape(
        "Payload",
        (TypedDictField("value", INT, required=False, readonly=True),),
    )

    semantic = COMPILER_TYPE_SYSTEM.record(source)

    assert isinstance(semantic, Success)
    assert typed_dict_shape(semantic.unwrap()) == Success(source)
