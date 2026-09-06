import pytest

from typeforge.compiler.stub_ir import (
    StubTypeExpression,
    TypeName,
    UnionExpression,
    union_types,
)


@pytest.mark.parametrize(
    ("expressions", "expected"),
    [
        pytest.param((), TypeName("Never"), id="empty-union-is-never"),
        pytest.param(
            (TypeName("int"), TypeName("int")),
            TypeName("int"),
            id="duplicates-collapse-to-one-type",
        ),
        pytest.param(
            (TypeName("str"), UnionExpression((TypeName("int"), TypeName("str")))),
            UnionExpression((TypeName("str"), TypeName("int"))),
            id="union-members-keep-first-occurrence-order",
        ),
        pytest.param(
            (TypeName("Never"), TypeName("int")),
            UnionExpression((TypeName("Never"), TypeName("int"))),
            id="explicit-never-members-are-preserved",
        ),
        pytest.param(
            (UnionExpression((UnionExpression((TypeName("int"), TypeName("str"))),)),),
            UnionExpression((TypeName("int"), TypeName("str"))),
            id="flatten-one-level-without-rebuilding-nested-members",
        ),
    ],
)
def test_union_composition_preserves_existing_projection_policy(
    expressions: tuple[StubTypeExpression, ...], expected: StubTypeExpression
) -> None:
    assert union_types(expressions) == expected


def test_single_union_member_is_retained_by_identity() -> None:
    member = UnionExpression((TypeName("int"), TypeName("str")))

    result = union_types((UnionExpression((member,)),))

    assert result is member
