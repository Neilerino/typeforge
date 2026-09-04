from pathlib import Path

from typeforge.compiler.module_surface import ModuleSurface, inspect_module_surface
from typeforge.compiler.source import parse_module
from typeforge.compiler.stub_ir import ImportFrom, TypeName, VariableDeclaration


def test_inspection_returns_public_module_variables_and_imports(
    tmp_path: Path,
) -> None:
    path = tmp_path / "surface.py"
    path.write_text(
        "from external import Parser\nanswer: int = 42\n",
        encoding="utf-8",
    )
    source = parse_module(path).unwrap()

    surface = inspect_module_surface(source).unwrap()

    assert surface == ModuleSurface(
        declarations=(VariableDeclaration("answer", TypeName("int")),),
        imports=(ImportFrom("external", ("Parser",)),),
    )
