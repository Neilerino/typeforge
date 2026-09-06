import ast
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from typeforge.compiler.module_surface import ModuleSurface, inspect_module_surface
from typeforge.compiler.source import parse_module, parse_source
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


def test_inspection_uses_in_memory_syntax_for_exports_and_variables() -> None:
    source = dedent("""\
        from external import Parser, Builder as Factory
        from typeforge import Map
        __all__ = ("Parser", "Factory", "payload")
        payload = []  # type: list[Any]
        count, label = 42, "ready"
        fail_if_executed()
        """)
    parsed = parse_source(source, path=Path("missing/surface.py")).unwrap()
    parse_expression = ast.parse

    def annotation_only(annotation: str, *, mode: str = "exec") -> ast.Expression:
        assert mode == "eval", "surface inspection must not reparse authored modules"
        return parse_expression(annotation, mode="eval")

    with (
        patch.object(Path, "read_text", side_effect=AssertionError("unexpected read")),
        patch("ast.parse", side_effect=annotation_only),
    ):
        surface = inspect_module_surface(parsed).unwrap()

    assert surface == ModuleSurface(
        declarations=(
            VariableDeclaration("payload", TypeName("list[Any]")),
            VariableDeclaration("count", TypeName("int")),
            VariableDeclaration("label", TypeName("str")),
        ),
        imports=(
            ImportFrom("external", ("Builder as Factory", "Parser as Parser")),
            ImportFrom("typing", ("Any",)),
        ),
    )
