from returns.result import Failure

from tests.unit.semantics.test_migration_spec import NameTypeSystem
from typeforge import semantics as s

FIELD = s.TypeSymbol(("test-field",), "field")


def test_annotations_preserve_record_metadata_order_without_mutating_source() -> None:
    source = s.RecordShape(
        s.RecordFamily.TYPED_DICT, "User", (s.RecordField("name", "str"),)
    )
    adapter = NameTypeSystem(records=(("User", source),))
    copied = s.RecordExpression(
        s.TypeReference("User"),
        FIELD,
        s.FieldExpression(s.FieldNameReference(FIELD), s.FieldTypeReference(FIELD)),
    )
    expression = s.AnnotatedExpression(
        "Annotated", s.AnnotatedExpression("Annotated", copied, ("inner",)), ("outer",)
    )

    result = s.evaluate(expression, adapter).unwrap()

    assert isinstance(result, s.RecordShape)
    assert result.metadata == ("inner", "outer")
    assert result.fields == source.fields
    assert source.metadata == ()


def test_annotation_preserves_inner_failures_instead_of_trying_to_build_a_type() -> (
    None
):
    result = s.evaluate(
        s.AnnotatedExpression("Annotated", s.FieldNameReference(FIELD), ("opaque",)),
        NameTypeSystem(),
    )

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), s.UnboundFieldSemanticError)
