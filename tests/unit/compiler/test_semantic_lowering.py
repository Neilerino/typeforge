from pathlib import Path

import pytest
from returns.result import Success

from typeforge.compiler._semantic_lowering import (
    SemanticLoweringError,
    lower_semantic_expression,
)
from typeforge.compiler._type_system import COMPILER_TYPE_SYSTEM
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SourcePosition,
    SourceSpan,
    TypeExpression,
)
from typeforge.compiler.records import (
    NamedType,
    ParameterizedType,
    StaticType,
    UnionType,
)
from typeforge.semantics import (
    CaptureValuePattern,
    CaseExpression,
    DeferredMap,
    EvaluationContext,
    FieldExpression,
    FieldName,
    InputReference,
    KeyReference,
    MapExpression,
    MapFieldsExpression,
    ParameterizedTypePattern,
    ParameterizedTypeTemplate,
    RecordFamily,
    RecordShape,
    ResolvedType,
    TypeReference,
    ValueReference,
    evaluate,
)

SPAN = SourceSpan(Path("records.py"), SourcePosition(1, 0), SourcePosition(1, 1))


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
    """`Case[list[Value], set[Value]]` lowers to a pattern and template."""
    value = marker(MarkerKind.VALUE)
    expression = marker(
        MarkerKind.MAP,
        name("T"),
        marker(
            MarkerKind.CASE,
            AppliedTypeExpression(
                source="list[Value]",
                span=SPAN,
                constructor=name("list"),
                arguments=(value,),
            ),
            AppliedTypeExpression(
                source="set[Value]",
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
                    (CaptureValuePattern(),),
                ),
                ParameterizedTypeTemplate(
                    NamedType("set"),
                    (ValueReference(),),
                ),
            ),
        ),
        TypeReference(NamedType("T")),
    )


def test_input_map_lowers_and_evaluates_to_a_deferred_map() -> None:
    """`Map[Input, Case[int, int], ...]` lowers to deferred semantics."""
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

    assert lower_semantic_expression(literal, ()) == FieldName("token")


def test_field_name_map_preserves_string_literal_names() -> None:
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
        MarkerKind.FIELD,
        marker(
            MarkerKind.MAP,
            marker(MarkerKind.KEY),
            marker(MarkerKind.CASE, source, target),
            marker(MarkerKind.DEFAULT, marker(MarkerKind.KEY)),
        ),
        name("int"),
    )

    assert lower_semantic_expression(expression, ()) == FieldExpression(
        MapExpression(
            KeyReference(),
            (CaseExpression(FieldName("source"), FieldName("target")),),
            KeyReference(),
        ),
        TypeReference(NamedType("int")),
    )


def test_record_markers_lower_to_the_shared_semantic_model() -> None:
    payload: StaticType = RecordShape[StaticType](
        family=RecordFamily.TYPED_DICT,
        name="Payload",
        fields=(),
    )
    expression = marker(
        MarkerKind.MAP_FIELDS,
        name("T"),
        marker(
            MarkerKind.FIELD,
            marker(MarkerKind.KEY),
            marker(
                MarkerKind.MAP,
                marker(MarkerKind.VALUE),
                marker(MarkerKind.CASE, name("datetime"), name("str")),
                marker(MarkerKind.DEFAULT, marker(MarkerKind.VALUE)),
            ),
        ),
    )

    expected: MapFieldsExpression[StaticType] = MapFieldsExpression(
        TypeReference(payload),
        FieldExpression(
            KeyReference(),
            MapExpression(
                ValueReference(),
                (
                    CaseExpression(
                        TypeReference(NamedType("datetime")),
                        TypeReference(NamedType("str")),
                    ),
                ),
                ValueReference(),
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
    *arguments: TypeExpression,
) -> MarkerTypeExpression:
    return MarkerTypeExpression(kind.value, SPAN, kind, arguments)
