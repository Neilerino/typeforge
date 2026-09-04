from returns.result import Failure

from typeforge.compiler.emission import EmissionError, emit_type_expression
from typeforge.compiler.stub_ir import EachType, TypeName


def test_unlowered_type_expression_returns_a_modeled_emission_error() -> None:
    result = emit_type_expression(EachType(TypeName("int")))

    assert result == Failure(EmissionError("unlowered type expression: EachType"))
