from returns.result import Failure

from typeforge.compiler.emission import (
    EmissionError,
    emit_stub_module,
    emit_type_expression,
)
from typeforge.compiler.specialization import ArityFrontier, lower_variadic_module
from typeforge.compiler.stub_ir import (
    EachType,
    FunctionDeclaration,
    LiteralType,
    StubModule,
    TypeAliasDeclaration,
    TypeName,
)


def test_reusable_roots_keep_identity_without_emitting_declarations_or_imports() -> (
    None
):
    literal = LiteralType("'ready'")
    unlowered = EachType(TypeName("int"))
    contract = FunctionDeclaration("unemitted", (), unlowered)
    module = StubModule(
        "example",
        (TypeAliasDeclaration("Number", TypeName("int")),),
        reusable_elements=(literal, unlowered, contract),
    )

    specialized = lower_variadic_module(module, ArityFrontier(0, 1)).unwrap()

    assert specialized.reusable_elements[0] is literal
    assert specialized.reusable_elements[1] is unlowered
    assert specialized.reusable_elements[2] is contract
    assert specialized.imports == ()
    assert emit_stub_module(specialized).unwrap() == "type Number = int\n"


def test_unlowered_type_expression_returns_a_modeled_emission_error() -> None:
    result = emit_type_expression(EachType(TypeName("int")))

    assert result == Failure(EmissionError("unlowered type expression: EachType"))
