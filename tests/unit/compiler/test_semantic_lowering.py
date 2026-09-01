from pathlib import Path

import pytest

from typeforge.compiler._semantic_lowering import (
    SemanticLoweringError,
    lower_semantic_expression,
)
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    SourcePosition,
    SourceSpan,
    TypeExpression,
)
from typeforge.compiler.records import NamedType, StaticType
from typeforge.semantics import (
    CaseExpression,
    FieldExpression,
    FieldName,
    KeyReference,
    MapExpression,
    MapFieldsExpression,
    RecordFamily,
    RecordShape,
    TypeReference,
    ValueReference,
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


def test_string_literal_lowers_to_a_field_name() -> None:
    literal = AppliedTypeExpression(
        'Literal["token"]',
        SPAN,
        name("Literal"),
        (RawTypeExpression('"token"', SPAN),),
    )

    assert lower_semantic_expression(literal, ()) == FieldName("token")


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
