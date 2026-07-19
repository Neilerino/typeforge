from typeforge.compiler._type_tree import rewrite_type, walk_type
from typeforge.compiler.lowering import (
    AllPredicate,
    EqualPredicate,
    MapCase,
    MapType,
    NotPredicate,
    TypeApplication,
    TypeName,
    TypeVariable,
)


def test_rewrite_is_top_down_and_does_not_rewrite_replacements() -> None:
    expression = TypeApplication(TypeName("Box"), (TypeVariable("T"),))

    rewritten = rewrite_type(
        expression,
        lambda item: (
            TypeApplication(TypeName("Replacement"), (TypeVariable("T"),))
            if item == expression
            else TypeName("unexpected")
        ),
    )

    assert rewritten == TypeApplication(
        TypeName("Replacement"),
        (TypeVariable("T"),),
    )


def test_rewrite_and_walk_include_predicate_and_map_operands() -> None:
    expression = MapType(
        TypeVariable("T"),
        (
            MapCase(
                AllPredicate(
                    (
                        EqualPredicate(TypeVariable("T"), TypeName("int")),
                        NotPredicate(
                            EqualPredicate(TypeName("str"), TypeVariable("T"))
                        ),
                    )
                ),
                MapType(
                    TypeVariable("T"),
                    (MapCase(TypeName("int"), TypeVariable("T")),),
                    TypeVariable("T"),
                ),
            ),
        ),
        TypeVariable("T"),
    )

    rewritten = rewrite_type(
        expression,
        lambda item: TypeName("bytes") if item == TypeVariable("T") else None,
    )

    assert TypeVariable("T") not in tuple(walk_type(rewritten))
    assert sum(item == TypeName("bytes") for item in walk_type(rewritten)) == 7
