from returns.result import Failure, Success

from typeforge.compiler.evaluator import (
    All,
    Any,
    Assignable,
    Case,
    Drop,
    DroppedField,
    Equal,
    EvaluationErrorCode,
    Field,
    FieldName,
    If,
    Key,
    Map,
    MapFields,
    Not,
    OptionalField,
    ReadonlyField,
    Value,
    evaluate,
)
from typeforge.compiler.records import (
    NEVER,
    NamedType,
    TypedDictField,
    TypedDictShape,
    UnionType,
)

INT = NamedType("int", ("object",))
STR = NamedType("str", ("object",))
BYTES = NamedType("bytes", ("object",))
OBJECT = NamedType("object")
DATETIME = NamedType("datetime", ("object",))


def test_conditions_compose() -> None:
    expression = All(
        (
            Equal(INT, INT),
            Assignable(INT, OBJECT),
            Not(Any((Equal(INT, STR), Equal(INT, BYTES)))),
        )
    )

    assert evaluate(expression) == Success(True)
    assert evaluate(If(expression, STR, BYTES)) == Success(STR)


def test_all_returns_false_and_short_circuits() -> None:
    expression = All((Equal(INT, STR), Key()))

    assert evaluate(expression) == Success(False)


def test_assignable_understands_union_sources_and_targets() -> None:
    assert evaluate(Assignable(UnionType((INT, STR)), OBJECT)) == Success(True)
    assert evaluate(Assignable(INT, UnionType((STR, OBJECT)))) == Success(True)
    assert evaluate(Assignable(UnionType((INT, STR)), INT)) == Success(False)


def test_map_matches_exact_types_and_uses_default() -> None:
    expression = Map(
        UnionType((INT, BYTES, DATETIME)),
        (Case(INT, STR), Case(BYTES, STR)),
        DATETIME,
    )

    assert evaluate(expression) == Success(UnionType((STR, DATETIME)))


def test_map_defaults_to_never() -> None:
    assert evaluate(Map(BYTES, (Case(INT, STR),))) == Success(NEVER)


def test_map_fields_transforms_typed_dict_values() -> None:
    source = TypedDictShape(
        "User",
        (
            TypedDictField("name", STR),
            TypedDictField("created_at", DATETIME),
            TypedDictField("attempts", INT),
        ),
    )
    transform = Field(
        Key(),
        Map(Value(), (Case(DATETIME, STR),), Value()),
    )

    result = evaluate(MapFields(source, transform, "JsonUser"))

    assert result == Success(
        TypedDictShape(
            "JsonUser",
            (
                TypedDictField("name", STR),
                TypedDictField("created_at", STR),
                TypedDictField("attempts", INT),
            ),
        )
    )


def test_map_fields_can_drop_and_change_field_modifiers() -> None:
    source = TypedDictShape(
        "Credentials",
        (
            TypedDictField("password", STR),
            TypedDictField("token", STR),
            TypedDictField("attempts", INT),
        ),
    )
    transform = If(
        Equal(Key(), FieldName("password")),
        Drop(),
        If(
            Equal(Key(), FieldName("token")),
            ReadonlyField(Key(), Value()),
            OptionalField(Key(), Value()),
        ),
    )

    result = evaluate(MapFields(source, transform))

    assert result == Success(
        TypedDictShape(
            "Credentials",
            (
                TypedDictField("token", STR, readonly=True),
                TypedDictField("attempts", INT, required=False),
            ),
        )
    )


def test_drop_is_an_explicit_evaluation_value() -> None:
    assert evaluate(Drop()) == Success(DroppedField())


def test_unbound_field_placeholders_are_typed_failures() -> None:
    key_result = evaluate(Key())
    value_result = evaluate(Value())

    assert isinstance(key_result, Failure)
    assert key_result.failure().code is EvaluationErrorCode.UNBOUND_KEY
    assert isinstance(value_result, Failure)
    assert value_result.failure().code is EvaluationErrorCode.UNBOUND_VALUE


def test_nested_failures_preserve_the_original_typed_error() -> None:
    result = evaluate(Equal(Key(), Key()))

    assert isinstance(result, Failure)
    assert result.failure().code is EvaluationErrorCode.UNBOUND_KEY


def test_invalid_field_name_has_the_specific_error_code() -> None:
    result = evaluate(Field(INT, STR))

    assert isinstance(result, Failure)
    assert result.failure().code is EvaluationErrorCode.EXPECTED_FIELD_NAME


def test_map_fields_rejects_non_record_input() -> None:
    result = evaluate(MapFields(INT, Field(Key(), Value())))

    assert isinstance(result, Failure)
    assert result.failure().code is EvaluationErrorCode.EXPECTED_TYPED_DICT
