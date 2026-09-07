from returns.result import Failure

from tests.unit.semantics.test_migration_spec import NameTypeSystem
from typeforge import semantics as s


def test_annotations_preserve_record_metadata_order_without_mutating_source() -> None:
    source = s.RecordShape(
        s.RecordFamily.TYPED_DICT, "User", (s.RecordField("name", "str"),)
    )
    adapter = NameTypeSystem(records=(("User", source),))
    copied = s.MapFieldsExpression(
        s.TypeReference("User"), s.FieldExpression(s.KeyReference(), s.ValueReference())
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
        s.AnnotatedExpression("Annotated", s.KeyReference(), ("opaque",)),
        NameTypeSystem(),
    )

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), s.UnboundKeySemanticError)
