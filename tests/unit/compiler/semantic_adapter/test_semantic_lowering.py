from pathlib import Path

import pytest
from returns.result import Success

from typeforge.compiler.semantic_adapter import (
    COMPILER_TYPE_SYSTEM,
    NamedType,
    ParameterizedType,
    SemanticLoweringError,
    StaticType,
    UnionType,
    lower_semantic_expression,
)
from typeforge.compiler.source import (
    AppliedTypeExpression,
    CaptureTypeExpression,
    FieldConstructionTypeExpression,
    FieldReferenceTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RecordTypeExpression,
    RuntimeInputTypeExpression,
    SourcePosition,
    SourceSpan,
    SourceTypeExpression,
    UnionTypeExpression,
)
from typeforge.semantics import (
    CaptureReference,
    CaseExpression,
    DeferredMap,
    EvaluationContext,
    FieldExpression,
    FieldName,
    FieldNameReference,
    FieldTypeReference,
    InputReference,
    MapExpression,
    ParameterizedTypePattern,
    ParameterizedTypeTemplate,
    RecordExpression,
    RecordFamily,
    RecordField,
    RecordShape,
    ResolvedType,
    TypeReference,
    TypeSymbol,
    evaluate,
)

SPAN = SourceSpan(Path("records.py"), SourcePosition(1, 0), SourcePosition(1, 1))


FIELD = TypeSymbol(
    (str(SPAN.path), str(SPAN.start.line), str(SPAN.start.column)), "field"
)


def test_names_lower_to_bound_or_named_type_references() -> None:
    payload: StaticType = RecordShape[StaticType](
        family=RecordFamily.TYPED_DICT,
        name="Payload",
        fields=(),
    )

    assert lower_semantic_expression(name("T"), (("T", payload),)) == TypeReference(
        payload
    )
    assert lower_semantic_expression(name("bytes"), ()) == TypeReference(
        NamedType("bytes")
    )


def test_parameterized_type_lowers_to_a_structured_compiler_type() -> None:
    """`list[int]` lowers to a reference containing `ParameterizedType`."""
    expression = AppliedTypeExpression(
        source="list[int]",
        span=SPAN,
        constructor=name("list"),
        arguments=(name("int"),),
    )

    assert lower_semantic_expression(expression, ()) == TypeReference(
        ParameterizedType(NamedType("list"), (NamedType("int"),))
    )


def test_map_lowers_parameterized_case_roles_to_shared_semantics() -> None:
    """`Case[list[Item], set[Item]]` lowers to a pattern and template."""
    value = CaptureTypeExpression("Item", SPAN, "Item", SPAN)
    capture = CaptureReference(
        TypeSymbol(
            (str(SPAN.path), str(SPAN.start.line), str(SPAN.start.column)), "Item"
        )
    )
    expression = marker(
        MarkerKind.MAP,
        name("T"),
        marker(
            MarkerKind.CASE,
            AppliedTypeExpression(
                source="list[Item]",
                span=SPAN,
                constructor=name("list"),
                arguments=(value,),
            ),
            AppliedTypeExpression(
                source="set[Item]",
                span=SPAN,
                constructor=name("set"),
                arguments=(value,),
            ),
        ),
        marker(MarkerKind.DEFAULT, name("T")),
    )

    assert lower_semantic_expression(expression, ()) == MapExpression(
        TypeReference(NamedType("T")),
        (
            CaseExpression(
                ParameterizedTypePattern(
                    NamedType("list"),
                    (capture,),
                ),
                ParameterizedTypeTemplate(
                    NamedType("set"),
                    (capture,),
                ),
            ),
        ),
        TypeReference(NamedType("T")),
    )


def test_input_map_lowers_and_evaluates_to_a_deferred_map() -> None:
    """`Map[Input, int : int, ...]` lowers to deferred semantics."""
    cases: tuple[CaseExpression[StaticType], ...] = (
        CaseExpression(
            TypeReference(NamedType("int")),
            TypeReference(NamedType("int")),
        ),
        CaseExpression(
            TypeReference(NamedType("str")),
            TypeReference(NamedType("UUID")),
        ),
    )
    default = TypeReference[StaticType](NamedType("bytes"))
    expression = marker(
        MarkerKind.MAP,
        RuntimeInputTypeExpression("Input", SPAN),
        marker(MarkerKind.CASE, name("int"), name("int")),
        marker(MarkerKind.CASE, name("str"), name("UUID")),
        marker(MarkerKind.DEFAULT, name("bytes")),
    )

    lowered = lower_semantic_expression(expression, ())

    assert lowered == MapExpression(InputReference(), cases, default)
    assert evaluate(lowered, COMPILER_TYPE_SYSTEM) == Success(
        DeferredMap(
            cases=cases,
            default=default,
            context=EvaluationContext(),
            possible_output=ResolvedType(
                UnionType(
                    NamedType("int"),
                    NamedType("UUID"),
                    NamedType("bytes"),
                )
            ),
        )
    )


def test_string_literal_lowers_to_a_field_name() -> None:
    literal = AppliedTypeExpression(
        source='Literal["token"]',
        span=SPAN,
        constructor=name("Literal"),
        arguments=(RawTypeExpression('"token"', SPAN),),
    )

    assert lower_semantic_expression(literal, (), role="field-name") == FieldName(
        "token"
    )


def test_map_case_preserves_string_literal_field_names() -> None:
    source = AppliedTypeExpression(
        source='Literal["source"]',
        span=SPAN,
        constructor=name("Literal"),
        arguments=(RawTypeExpression('"source"', SPAN),),
    )
    target = AppliedTypeExpression(
        source='Literal["target"]',
        span=SPAN,
        constructor=name("Literal"),
        arguments=(RawTypeExpression('"target"', SPAN),),
    )
    expression = marker(
        MarkerKind.MAP,
        FieldReferenceTypeExpression(
            "field.name", SPAN, "field", SPAN, attribute="name"
        ),
        marker(MarkerKind.CASE, source, target),
    )

    assert lower_semantic_expression(
        expression, (), role="field-name"
    ) == MapExpression(
        FieldNameReference(FIELD),
        (CaseExpression(FieldName("source"), FieldName("target")),),
    )


def test_record_markers_lower_to_the_shared_semantic_model() -> None:
    payload: StaticType = RecordShape[StaticType](
        family=RecordFamily.TYPED_DICT,
        name="Payload",
        fields=(),
    )
    expression = RecordTypeExpression(
        "Record(...)",
        SPAN,
        name("T"),
        FieldReferenceTypeExpression("field", SPAN, "field", SPAN),
        FieldConstructionTypeExpression(
            "Field(...)",
            SPAN,
            FieldReferenceTypeExpression(
                "field.name", SPAN, "field", SPAN, attribute="name"
            ),
            marker(
                MarkerKind.MAP,
                FieldReferenceTypeExpression(
                    "field.type", SPAN, "field", SPAN, attribute="type"
                ),
                marker(MarkerKind.CASE, name("datetime"), name("str")),
                marker(
                    MarkerKind.DEFAULT,
                    FieldReferenceTypeExpression(
                        "field.type", SPAN, "field", SPAN, attribute="type"
                    ),
                ),
            ),
        ),
    )

    expected: RecordExpression[StaticType] = RecordExpression(
        TypeReference(payload),
        FIELD,
        FieldExpression(
            FieldNameReference(FIELD),
            MapExpression(
                FieldTypeReference(FIELD),
                (
                    CaseExpression(
                        TypeReference(NamedType("datetime")),
                        TypeReference(NamedType("str")),
                    ),
                ),
                FieldTypeReference(FIELD),
            ),
        ),
        "JsonPayload",
    )

    assert (
        lower_semantic_expression(
            expression,
            (("T", payload),),
            "JsonPayload",
        )
        == expected
    )


def test_map_without_a_default_preserves_omission() -> None:
    expression = marker(
        MarkerKind.MAP,
        name("int"),
        marker(MarkerKind.CASE, name("int"), name("str")),
    )

    assert lower_semantic_expression(expression, ()) == MapExpression(
        TypeReference(NamedType("int")),
        (
            CaseExpression(
                TypeReference(NamedType("int")),
                TypeReference(NamedType("str")),
            ),
        ),
    )


def test_marker_normalization_failures_remain_lowering_failures() -> None:
    with pytest.raises(
        SemanticLoweringError,
        match="Equal requires two type arguments",
    ):
        lower_semantic_expression(
            marker(MarkerKind.EQUAL, name("int")),
            (),
        )


def test_unsupported_normalized_markers_fail_explicitly() -> None:
    with pytest.raises(
        SemanticLoweringError, match="unsupported record expression Each"
    ):
        lower_semantic_expression(
            marker(MarkerKind.EACH, name("int")),
            (),
        )


def name(value: str) -> NameTypeExpression:
    return NameTypeExpression(value, SPAN, (value,), None)


def marker(
    kind: MarkerKind,
    *arguments: SourceTypeExpression,
) -> MarkerTypeExpression:
    return MarkerTypeExpression(kind.value, SPAN, kind, arguments)


def application(
    constructor: str, *arguments: SourceTypeExpression
) -> AppliedTypeExpression:
    return AppliedTypeExpression(
        source=f"{constructor}[{', '.join(argument.source for argument in arguments)}]",
        span=SPAN,
        constructor=name(constructor),
        arguments=arguments,
    )


@pytest.mark.parametrize("nested", (False, True))
def test_capture_output_role_composes_through_unions(nested: bool) -> None:
    value = CaptureTypeExpression("Item", SPAN, "Item", SPAN)
    output = (
        application(
            "tuple", UnionTypeExpression("Item | None", SPAN, (value, name("None")))
        )
        if nested
        else UnionTypeExpression(
            "set[Item] | None", SPAN, (application("set", value), name("None"))
        )
    )
    expression = marker(
        MarkerKind.MAP,
        application("list", name("int")),
        marker(MarkerKind.CASE, application("list", value), output),
    )
    integer = NamedType("int")
    none = NamedType("None")
    expected = (
        ParameterizedType(NamedType("tuple"), (UnionType(integer, none),))
        if nested
        else UnionType(ParameterizedType(NamedType("set"), (integer,)), none)
    )

    assert evaluate(
        lower_semantic_expression(expression, ()), COMPILER_TYPE_SYSTEM
    ) == Success(ResolvedType(expected))


@pytest.mark.parametrize("kind", (MarkerKind.EQUAL, MarkerKind.ASSIGNABLE))
def test_literal_predicate_operands_remain_types(kind: MarkerKind) -> None:
    literal = application("Literal", RawTypeExpression('"accepted"', SPAN))
    expression = marker(kind, literal, literal)

    assert evaluate(
        lower_semantic_expression(expression, ()), COMPILER_TYPE_SYSTEM
    ) == Success(True)


def test_literal_case_and_default_outputs_remain_types() -> None:
    literal = application("Literal", RawTypeExpression('"accepted"', SPAN))
    expression = marker(
        MarkerKind.MAP,
        literal,
        marker(MarkerKind.CASE, literal, literal),
        marker(MarkerKind.DEFAULT, literal),
    )
    expected = ParameterizedType(NamedType("Literal"), (NamedType('"accepted"'),))

    assert evaluate(
        lower_semantic_expression(expression, ()), COMPILER_TYPE_SYSTEM
    ) == Success(ResolvedType(expected))


def test_literal_type_output_inside_a_transformed_field() -> None:
    literal = application("Literal", RawTypeExpression('"accepted"', SPAN))
    expression = FieldConstructionTypeExpression(
        "Field(...)",
        SPAN,
        FieldReferenceTypeExpression(
            "field.name", SPAN, "field", SPAN, attribute="name"
        ),
        marker(
            MarkerKind.MAP,
            FieldReferenceTypeExpression(
                "field.type", SPAN, "field", SPAN, attribute="type"
            ),
            marker(MarkerKind.CASE, name("int"), literal),
            marker(MarkerKind.DEFAULT, name("bytes")),
        ),
    )

    result = evaluate(
        lower_semantic_expression(expression, ()),
        COMPILER_TYPE_SYSTEM,
        EvaluationContext[StaticType](
            fields=((FIELD, RecordField("original", NamedType("int"))),)
        ),
    )

    assert result == Success(
        RecordField(
            "original",
            ParameterizedType(NamedType("Literal"), (NamedType('"accepted"'),)),
        )
    )


def test_key_map_can_compare_literal_field_types() -> None:
    literal = application("Literal", RawTypeExpression('"accepted"', SPAN))
    expression = marker(
        MarkerKind.MAP,
        FieldReferenceTypeExpression(
            "field.name", SPAN, "field", SPAN, attribute="name"
        ),
        marker(
            MarkerKind.CASE,
            marker(
                MarkerKind.EQUAL,
                FieldReferenceTypeExpression(
                    "field.type", SPAN, "field", SPAN, attribute="type"
                ),
                literal,
            ),
            FieldConstructionTypeExpression(
                "Field(...)",
                SPAN,
                FieldReferenceTypeExpression(
                    "field.name", SPAN, "field", SPAN, attribute="name"
                ),
                name("str"),
            ),
        ),
        marker(
            MarkerKind.DEFAULT,
            FieldConstructionTypeExpression(
                "Field(...)",
                SPAN,
                FieldReferenceTypeExpression(
                    "field.name", SPAN, "field", SPAN, attribute="name"
                ),
                name("bytes"),
            ),
        ),
    )
    literal_type = ParameterizedType(NamedType("Literal"), (NamedType('"accepted"'),))

    assert evaluate(
        lower_semantic_expression(expression, ()),
        COMPILER_TYPE_SYSTEM,
        EvaluationContext[StaticType](
            fields=((FIELD, RecordField("value", literal_type)),)
        ),
    ) == Success(RecordField("value", NamedType("str")))
