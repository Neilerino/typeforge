from pathlib import Path

from returns.result import Success

from typeforge.compiler.source import SourcePosition, SourceSpan
from typeforge.compiler.specialization import ArityFrontier, lower_variadic_module
from typeforge.compiler.stub_ir import (
    CollectType,
    EachType,
    FunctionDeclaration,
    GeneratedElementOrigin,
    OverloadDeclaration,
    Parameter,
    ParameterKind,
    StubModule,
    TypeVariable,
)


def variadic_function() -> FunctionDeclaration:
    captured = TypeVariable("Ts")
    return FunctionDeclaration(
        "collect",
        (Parameter("values", EachType(captured), ParameterKind.VAR_POSITIONAL),),
        CollectType(captured),
        ("*Ts",),
    )


def test_lower_variadic_module_carries_origin_to_generated_overload() -> None:
    original_function = variadic_function()
    span = SourceSpan(
        Path("callables.py"),
        SourcePosition(1, 0),
        SourcePosition(1, 62),
    )
    result = lower_variadic_module(
        StubModule(
            "callables",
            (original_function,),
            origins=(GeneratedElementOrigin(span, original_function),),
        ),
        ArityFrontier(0, 1),
    )

    assert isinstance(result, Success)
    specialized = result.unwrap()
    generated_overload = next(
        declaration
        for declaration in specialized.declarations
        if isinstance(declaration, OverloadDeclaration)
    )
    assert specialized.origins == (GeneratedElementOrigin(span, generated_overload),)


def test_lower_variadic_module_rewrites_equal_declarations_by_identity() -> None:
    first = variadic_function()
    second = variadic_function()
    first_span = SourceSpan(
        Path("callables.py"),
        SourcePosition(1, 0),
        SourcePosition(1, 62),
    )
    second_span = SourceSpan(
        Path("callables.py"),
        SourcePosition(2, 0),
        SourcePosition(2, 62),
    )

    result = lower_variadic_module(
        StubModule(
            "callables",
            (first, second),
            origins=(
                GeneratedElementOrigin(first_span, first),
                GeneratedElementOrigin(second_span, second),
            ),
        ),
        ArityFrontier(0, 1),
    )

    assert isinstance(result, Success)
    specialized = result.unwrap()
    assert specialized.origins[0].generated is specialized.declarations[0]
    assert specialized.origins[1].generated is specialized.declarations[1]
