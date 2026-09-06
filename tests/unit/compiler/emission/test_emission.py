from returns.result import Failure

from typeforge.compiler.emission import (
    EmissionError,
    emit_stub_module,
    emit_type_expression,
)
from typeforge.compiler.specialization import ArityFrontier, lower_variadic_module
from typeforge.compiler.stub_ir import (
    EachType,
    LiteralType,
    StubModule,
    TypeAliasDeclaration,
    TypeName,
)


def test_unemitted_expression_roots_preserve_identity_without_adding_imports() -> None:
    literal = LiteralType("'ready'")
    unlowered = EachType(TypeName("int"))
    module = StubModule(
        "example",
        (TypeAliasDeclaration("Number", TypeName("int")),),
        expressions=(literal, unlowered),
    )

    specialized = lower_variadic_module(module, ArityFrontier(0, 1)).unwrap()

    assert specialized.expressions[0] is literal
    assert specialized.expressions[1] is unlowered
    assert specialized.imports == ()
    assert emit_stub_module(specialized).unwrap() == "type Number = int\n"


def test_unlowered_type_expression_returns_a_modeled_emission_error() -> None:
    result = emit_type_expression(EachType(TypeName("int")))

    assert result == Failure(EmissionError("unlowered type expression: EachType"))
