from typeforge._result import Err, Ok
from typeforge.compiler.evaluator import (
    All,
    Any,
    Assignable,
    Case,
    Drop,
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
    evaluate_map_fields,
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

    assert evaluate(expression) == Ok(True)
    assert evaluate(If(expression, STR, BYTES)) == Ok(STR)


def test_assignable_understands_union_sources_and_targets() -> None:
    assert evaluate(Assignable(UnionType((INT, STR)), OBJECT)) == Ok(True)
    assert evaluate(Assignable(INT, UnionType((STR, OBJECT)))) == Ok(True)
    assert evaluate(Assignable(UnionType((INT, STR)), INT)) == Ok(False)


def test_map_matches_exact_types_and_uses_default() -> None:
    expression = Map(
        UnionType((INT, BYTES, DATETIME)),
        (Case(INT, STR), Case(BYTES, STR)),
        DATETIME,
    )

    assert evaluate(expression) == Ok(UnionType((STR, DATETIME)))


def test_map_defaults_to_never() -> None:
    assert evaluate(Map(BYTES, (Case(INT, STR),))) == Ok(NEVER)


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

    result = evaluate_map_fields(MapFields(source, transform, "JsonUser"))

    assert result == Ok(
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

    result = evaluate_map_fields(MapFields(source, transform))

    assert result == Ok(
        TypedDictShape(
            "Credentials",
            (
                TypedDictField("token", STR, readonly=True),
                TypedDictField("attempts", INT, required=False),
            ),
        )
    )


def test_unbound_field_placeholders_are_typed_failures() -> None:
    key_result = evaluate(Key())
    value_result = evaluate(Value())

    assert isinstance(key_result, Err)
    assert key_result.error.code is EvaluationErrorCode.UNBOUND_KEY
    assert isinstance(value_result, Err)
    assert value_result.error.code is EvaluationErrorCode.UNBOUND_VALUE


def test_map_fields_rejects_non_record_input() -> None:
    result = evaluate_map_fields(MapFields(INT, Field(Key(), Value())))

    assert isinstance(result, Err)
    assert result.error.code is EvaluationErrorCode.EXPECTED_TYPED_DICT
