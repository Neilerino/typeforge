from pathlib import Path

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.source import parse_module
from typeforge.compiler.stub_ir import (
    FunctionDeclaration,
    Parameter,
    StubModule,
    TypeApplication,
    TypeName,
)


def test_adapt_source_module_translates_authored_types_to_stub_ir(
    tmp_path: Path,
) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        "def convert(items: list[int]) -> set[str]: ...\n",
        encoding="utf-8",
    )
    source = parse_module(path).unwrap()

    adapted = adapt_source_module(source).unwrap()

    assert adapted == StubModule(
        name="example",
        declarations=(
            FunctionDeclaration(
                name="convert",
                parameters=(
                    Parameter(
                        name="items",
                        annotation=TypeApplication(
                            constructor=TypeName("list"),
                            arguments=(TypeName("int"),),
                        ),
                    ),
                ),
                return_type=TypeApplication(
                    constructor=TypeName("set"),
                    arguments=(TypeName("str"),),
                ),
            ),
        ),
    )
