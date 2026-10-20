from typeforge.compiler.specialization import ArityFrontier, lower_variadic_module
from typeforge.compiler.stub_ir import (
    CollectType,
    EachType,
    FixedTuple,
    FunctionDeclaration,
    MapCase,
    MapType,
    OverloadDeclaration,
    Parameter,
    ParameterKind,
    StubModule,
    TypeName,
    TypeVariable,
    UnionExpression,
)


def test_mapped_each_emits_closed_products_then_one_complete_aggregate() -> None:
    captured = TypeVariable("T")
    mapping = MapType(
        captured,
        (
            MapCase(TypeName("int"), TypeName("str")),
            MapCase(TypeName("str"), TypeName("bytes")),
        ),
        TypeName("None"),
    )
    declaration = FunctionDeclaration(
        "mapped",
        (Parameter("items", EachType(captured), ParameterKind.VAR_POSITIONAL),),
        CollectType(mapping),
        ("T",),
    )
    result = lower_variadic_module(
        StubModule("example", (declaration,)), ArityFrontier(0, 2)
    ).unwrap()
    lowered = result.declarations[0]
    assert isinstance(lowered, OverloadDeclaration)
    assert len(lowered.signatures) == 9
    assert lowered.signatures[0].return_type == FixedTuple(())
    assert lowered.signatures[0].parameters == ()

    paired = lowered.signatures[4:]
    assert tuple(
        tuple(parameter.annotation for parameter in signature.parameters)
        for signature in paired
    ) == (
        (TypeName("int"), TypeName("int")),
        (TypeName("int"), TypeName("str")),
        (TypeName("str"), TypeName("int")),
        (TypeName("str"), TypeName("str")),
        (TypeVariable("T1"), TypeVariable("T2")),
    )
    assert tuple(signature.return_type for signature in paired[:4]) == (
        FixedTuple((TypeName("str"), TypeName("str"))),
        FixedTuple((TypeName("str"), TypeName("bytes"))),
        FixedTuple((TypeName("bytes"), TypeName("str"))),
        FixedTuple((TypeName("bytes"), TypeName("bytes"))),
    )
    output = UnionExpression((TypeName("str"), TypeName("bytes"), TypeName("None")))
    assert paired[-1].return_type == FixedTuple((output, output))
    assert paired[-1].type_parameters == ("T1", "T2")
