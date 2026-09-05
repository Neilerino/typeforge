from pathlib import Path

from returns.result import Failure, Success

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.pipeline import (
    RecordMaterializationError,
    compile_source,
    generate_module,
)
from typeforge.compiler.source import parse_source
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    ClassField,
    FunctionDeclaration,
    GeneratedElementOrigin,
    OverloadDeclaration,
    Parameter,
    ParameterKind,
    TypeName,
)


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


def test_compilation_preserves_metadata_when_rewriting_classes_and_methods() -> None:
    source = (
        "from typing import TypedDict\n"
        "from typeforge import Collect, Each, Field, Key, MapFields, Value\n"
        "class Payload(TypedDict):\n    value: int\n"
        "type Copy[T] = MapFields[T, Field[Key, Value]]\n"
        "@decorate\n"
        "class Consumer[U](Base, metaclass=Meta):\n"
        "    cached: Copy[Payload] = ...\n"
        "    @custom\n"
        "    async def collect[*Ts](self: object, *values: Each[Ts], "
        "label: str = 'label') -> Collect[Ts]: ...\n"
        "    @custom\n"
        "    async def read(self: object, *, value: Copy[Payload] = ...) "
        "-> Copy[Payload]: ...\n"
    )

    plan = compile_source(source, Path("metadata.py"), maximum_arity=1).unwrap()

    consumer = next(
        item
        for item in plan.module.declarations
        if isinstance(item, ClassDeclaration) and item.name == "Consumer"
    )
    assert consumer.bases == (TypeName("Base"),)
    assert consumer.type_parameters == ("U",)
    assert consumer.keywords == ("metaclass=Meta",)
    assert consumer.decorators == ("decorate",)
    assert consumer.fields == (ClassField("cached", TypeName("Copy_Payload"), "..."),)
    collect, read = consumer.methods
    assert isinstance(collect, OverloadDeclaration)
    assert isinstance(read, FunctionDeclaration)
    for signature in (*collect.signatures, collect.fallback, read):
        assert signature.is_async
        assert signature.decorators == ("custom",)

    for signature in (*collect.signatures, collect.fallback):
        assert signature.parameters[-1] == Parameter(
            "label", TypeName("str"), ParameterKind.KEYWORD_ONLY, "..."
        )

    assert read.return_type == TypeName("Copy_Payload")
    assert read.parameters[-1] == Parameter(
        "value", TypeName("Copy_Payload"), ParameterKind.KEYWORD_ONLY, "..."
    )


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
