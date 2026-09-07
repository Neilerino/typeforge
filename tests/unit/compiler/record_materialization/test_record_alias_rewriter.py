import pytest

from typeforge.compiler.record_materialization import DerivedRecord, RecordAliasRewriter
from typeforge.compiler.semantic_adapter import StaticType
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    ClassField,
    Declaration,
    FunctionDeclaration,
    OverloadDeclaration,
    Parameter,
    StubTypeExpression,
    TypeAliasDeclaration,
    TypeApplication,
    TypeName,
    VariableDeclaration,
    walk_declaration,
)
from typeforge.semantics import RecordFamily, RecordShape

ALIAS = TypeApplication(TypeName("Copy"), (TypeName("Payload"),))
DERIVED = (
    DerivedRecord(
        "Copy",
        "Payload",
        RecordShape[StaticType](RecordFamily.TYPED_DICT, "Copy_Payload", ()),
    ),
)
FUNCTION = FunctionDeclaration(
    "copy", (Parameter("value", ALIAS),), TypeApplication(TypeName("list"), (ALIAS,))
)


@pytest.mark.parametrize(
    "declaration",
    [
        TypeAliasDeclaration("Selected", ALIAS),
        VariableDeclaration("selected", ALIAS),
        ClassDeclaration(
            "Consumer",
            (ALIAS,),
            (ClassField("value", ALIAS),),
            (FUNCTION, OverloadDeclaration((FUNCTION,), FUNCTION, "overload")),
        ),
    ],
)
def test_one_rewriter_reaches_all_declaration_type_positions(
    declaration: Declaration,
) -> None:
    changes: list[tuple[StubTypeExpression, StubTypeExpression]] = []
    rewriter = RecordAliasRewriter(
        DERIVED, on_rewrite=lambda old, new: changes.append((old, new))
    )
    expected_replacements = sum(item == ALIAS for item in walk_declaration(declaration))

    rewritten = rewriter.rewrite_declaration(declaration)

    assert not any(item == ALIAS for item in walk_declaration(rewritten))
    assert (
        sum(item == TypeName("Copy_Payload") for item in walk_declaration(rewritten))
        == expected_replacements
    )
    replaced_aliases = [(old, new) for old, new in changes if old is ALIAS]
    assert len(replaced_aliases) == expected_replacements
    for _, replacement in replaced_aliases:
        assert replacement == TypeName("Copy_Payload")
        assert any(replacement is item for item in walk_declaration(rewritten))


def test_repeated_rewrites_keep_independent_root_identity() -> None:
    rewriter = RecordAliasRewriter(DERIVED)

    first = rewriter.rewrite_type(ALIAS)
    second = rewriter.rewrite_type(ALIAS)

    assert first == second == TypeName("Copy_Payload")
    assert first is not second
    unchanged = TypeApplication(TypeName("Copy"), (TypeName("Other"),))
    assert rewriter.rewrite_type(unchanged) is unchanged
    assert RecordAliasRewriter(()).rewrite_type(ALIAS) is ALIAS


def test_observer_failure_propagates_without_poisoning_the_rewriter() -> None:
    class ObserverError(Exception):
        pass

    def observe(old: StubTypeExpression, new: StubTypeExpression) -> None:
        if old is ALIAS:
            raise ObserverError("observer failed")

    rewriter = RecordAliasRewriter(DERIVED, on_rewrite=observe)

    with pytest.raises(ObserverError, match="observer failed"):
        rewriter.rewrite_type(ALIAS)

    unchanged = TypeName("int")
    assert rewriter.rewrite_type(unchanged) is unchanged
