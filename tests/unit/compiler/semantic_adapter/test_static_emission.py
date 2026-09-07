import pytest

from typeforge.compiler.semantic_adapter import (
    NEVER,
    NamedType,
    ParameterizedType,
    StaticType,
    UnionType,
    static_type_expression,
)
from typeforge.compiler.stub_ir import TypeApplication, TypeName, UnionExpression
from typeforge.semantics import RecordFamily, RecordShape


@pytest.mark.parametrize("never_name", ["Never", "tf_typing.Never"])
def test_static_emission_uses_one_never_policy_through_nested_types(
    never_name: str,
) -> None:
    value = ParameterizedType(
        NamedType("tuple"), (NEVER, UnionType(NamedType("str"), NEVER))
    )

    assert static_type_expression(value, never_name=never_name) == TypeApplication(
        TypeName("tuple"),
        (
            TypeName(never_name),
            UnionExpression((TypeName("str"), TypeName(never_name))),
        ),
    )


@pytest.mark.parametrize(
    ("name", "expected"), [("Payload", "Payload"), (None, "object")]
)
def test_record_references_use_their_materialized_name(
    name: str | None, expected: str
) -> None:
    value = RecordShape[StaticType](
        family=RecordFamily.TYPED_DICT, name=name, fields=()
    )

    assert static_type_expression(value, never_name="Never") == TypeName(expected)


def test_unpacked_types_emit_the_resolved_inner_type() -> None:
    from typeforge.compiler.semantic_adapter import UnpackedType
    from typeforge.compiler.stub_ir import UnpackedType as UnpackedExpression

    assert static_type_expression(
        UnpackedType(NEVER), never_name="tf_typing.Never"
    ) == UnpackedExpression(TypeName("tf_typing.Never"))
