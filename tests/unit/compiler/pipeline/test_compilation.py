from pathlib import Path

from returns.result import Failure, Success

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.pipeline import (
    RecordMaterializationError,
    compile_source,
    generate_module,
)
from typeforge.compiler.source import parse_source
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


def test_compile_source_keeps_record_origins_in_specialized_snapshot() -> None:
    plan = compile_source(
        "from typing import TypedDict\nclass Payload(TypedDict):\n    value: int\n",
        Path("records.py"),
        maximum_arity=1,
    ).unwrap()

    assert len(plan.module.origins) == 1
    assert plan.module.origins[0].origin == plan.source.typed_dicts[0].span
    assert plan.module.origins[0].generated is plan.module.declarations[0]


def test_record_failure_propagates_before_specialization(tmp_path: Path) -> None:
    source = (
        "from typing import TypedDict\n"
        "from typeforge import Field, Key, MapFields, Value\n"
        "class Payload(TypedDict):\n    value: int\n"
        "type Copy = MapFields[Payload, Field[Key, Value]]\n"
    )
    path = tmp_path / "records.py"
    path.write_text(source, encoding="utf-8")
    expected = RecordMaterializationError(
        declaration="Copy",
        expression="MapFields[Payload, Field[Key, Value]]",
        message="MapFields aliases require exactly one type parameter",
    )

    adapted = adapt_source_module(parse_source(source, path).unwrap())
    compiled = compile_source(source, path, maximum_arity=-1)
    generated = generate_module(path, maximum_arity=-1)

    assert adapted == Failure(expected)
    assert compiled == Failure(expected)
    assert generated == Failure(expected)
