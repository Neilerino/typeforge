from typeforge.compiler.stub_ir import (
    AllPredicate,
    EqualPredicate,
    MapCase,
    MapType,
    NotPredicate,
    StubModule,
    TypeAliasDeclaration,
    TypeApplication,
    TypeName,
    TypeVariable,
    rewrite_type,
    walk_module,
    walk_type,
)


def test_module_walk_visits_declarations_before_reusable_expression_roots() -> None:
    integer = TypeName("int")
    alias = TypeAliasDeclaration("Number", integer)
    string = TypeName("str")
    container = TypeName("list")
    reusable = TypeApplication(container, (string,))
    module = StubModule("example", (alias,), expressions=(reusable, integer))

    actual = tuple(walk_module(module))
    expected = (alias, integer, reusable, container, string, integer)

    assert len(actual) == len(expected)
    assert all(first is second for first, second in zip(actual, expected, strict=True))


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


def test_noop_rewrite_preserves_composite_identity() -> None:
    nested = TypeApplication(TypeName("list"), (TypeName("int"),))
    expression = MapType(
        TypeVariable("T"),
        (MapCase(EqualPredicate(nested, nested), nested),),
        nested,
    )

    assert rewrite_type(expression, lambda item: None) is expression


def test_equal_distinct_child_replacement_preserves_its_identity() -> None:
    original = TypeName("int")
    replacement = TypeName("int")
    expression = TypeApplication(TypeName("list"), (original,))

    rewritten = rewrite_type(
        expression, lambda item: replacement if item is original else None
    )

    assert rewritten == expression
    assert rewritten is not expression
    assert isinstance(rewritten, TypeApplication)
    assert rewritten.arguments[0] is replacement
    assert expression.arguments[0] is original
