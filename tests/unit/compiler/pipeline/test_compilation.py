from pathlib import Path

from returns.result import Success

from typeforge.compiler.pipeline import compile_source
from typeforge.compiler.stub_ir import GeneratedElementOrigin, OverloadDeclaration


def test_compile_source_associates_enriched_function_with_generated_overload() -> None:
    path = Path("callables.py")
    source = (
        "from typeforge import Collect, Each\n"
        "def identity[T](value: T) -> T: ...\n"
        "def collect[*Ts](*values: Each[Ts]) -> Collect[Ts]: ...\n"
    )

    result = compile_source(source, path, maximum_arity=1)

    assert isinstance(result, Success)
    plan = result.unwrap()
    identity, collect = plan.source.functions
    overload = next(
        declaration
        for declaration in plan.module.declarations
        if isinstance(declaration, OverloadDeclaration)
        and declaration.fallback.name == "collect"
    )
    assert plan.module.origins == (GeneratedElementOrigin(collect.span, overload),)
    assert all(item.origin != identity.span for item in plan.module.origins)
