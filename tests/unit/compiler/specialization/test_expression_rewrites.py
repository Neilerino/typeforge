from typeforge.compiler.specialization import ArityFrontier, lower_variadic_module
from typeforge.compiler.specialization._expressions import substitute_scalar
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    CollectType,
    EachType,
    FixedTuple,
    FunctionDeclaration,
    ImportFrom,
    LiteralType,
    MapCase,
    MapType,
    StubModule,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeVariable,
)


def test_scalar_substitution_preserves_nested_relationship_boundaries() -> None:
    variable = TypeVariable("T")
    mapping = MapType(
        variable, (MapCase(TypeName("int"), variable),), TypeName("object")
    )
    nested = (EachType(variable), CollectType(variable), mapping)
    original = FixedTuple((TypeApplication(TypeName("list"), (variable,)), *nested))
    rewrites: list[tuple[StubTypeExpression, StubTypeExpression]] = []
    result = substitute_scalar(
        original,
        "T",
        TypeName("str"),
        on_rewrite=lambda before, after: rewrites.append((before, after)),
    )
    assert result == FixedTuple(
        (TypeApplication(TypeName("list"), (TypeName("str"),)), *nested)
    )
    assert sum(before is variable for before, _ in rewrites) == 1
    assert rewrites[-1] == (original, result)
    for boundary in nested:
        assert any(
            before is boundary and after is boundary for before, after in rewrites
        )


def test_literal_type_parameter_bound_adds_required_import() -> None:
    declaration = FunctionDeclaration(
        "bounded",
        (),
        TypeName("None"),
        ("T",),
        type_parameter_domains=(("T", LiteralType("ready")),),
    )
    lowered = lower_variadic_module(
        StubModule("example", (declaration,)), ArityFrontier()
    ).unwrap()
    assert ImportFrom("typing", ("Literal",)) in lowered.imports


def test_literal_class_base_argument_adds_required_import() -> None:
    declaration = ClassDeclaration(
        "Ready",
        (TypeApplication(TypeName("State"), (LiteralType("ready"),)),),
        (),
        (),
    )
    lowered = lower_variadic_module(
        StubModule("example", (declaration,)), ArityFrontier()
    ).unwrap()
    assert ImportFrom("typing", ("Literal",)) in lowered.imports
