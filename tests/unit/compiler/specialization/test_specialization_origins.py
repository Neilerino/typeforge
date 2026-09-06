from dataclasses import replace
from pathlib import Path

from returns.result import Failure, Success

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.source import SourcePosition, SourceSpan, parse_source
from typeforge.compiler.specialization import (
    ArityFrontier,
    LoweringError,
    LoweringErrorCode,
    lower_variadic_module,
)
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    CollectType,
    EachType,
    FunctionDeclaration,
    GeneratedElementOrigin,
    OverloadDeclaration,
    Parameter,
    ParameterKind,
    StubModule,
    TypeVariable,
    walk_declaration,
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


def test_failed_method_lowering_preserves_input_snapshot_and_origins() -> None:
    valid = variadic_function()
    invalid = replace(valid, name="invalid", parameters=valid.parameters * 2)
    original = ClassDeclaration("Consumer", (), (), (valid, invalid))
    span = SourceSpan(Path("methods.py"), SourcePosition(2, 4), SourcePosition(2, 66))
    origin = GeneratedElementOrigin(span, valid)
    module = StubModule("methods", (original,), origins=(origin,))

    result = lower_variadic_module(module, ArityFrontier(0, 1))

    assert result == Failure(
        LoweringError(
            LoweringErrorCode.MULTIPLE_CAPTURES,
            "invalid",
            "a function must contain exactly one Each parameter",
        )
    )
    assert module.declarations[0] is original
    assert original.methods == (valid, invalid)
    assert module.origins == (origin,)
    assert module.origins[0].generated is valid


def test_failed_lowering_preserves_schema_origins_after_earlier_rewrites() -> None:
    source = parse_source(
        "from typeforge import Collect, Each\n"
        "from typeforge.pydantic import Schema\n"
        "def valid[*Ts](*values: Each[Schema[Ts]]) -> Collect[Schema[Ts]]: ...\n"
        "def invalid[*Ts](*values: Each[Ts], second: Each[Ts]) -> Collect[Ts]: ...\n",
        Path("schemas.py"),
    ).unwrap()
    module = adapt_source_module(source).unwrap()
    declarations = module.declarations
    origins = module.origins

    result = lower_variadic_module(module, ArityFrontier(0, 2))

    assert result == Failure(
        LoweringError(
            LoweringErrorCode.MULTIPLE_CAPTURES,
            "invalid",
            "a function must contain exactly one Each parameter",
        )
    )
    assert module.declarations is declarations
    assert module.origins is origins
    assert all(
        any(
            item.generated is element
            for declaration in declarations
            for element in walk_declaration(declaration)
        )
        for item in origins
    )
