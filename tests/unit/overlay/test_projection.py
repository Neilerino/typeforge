import ast
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from typeforge import overlay
from typeforge.analysis import MappingKind
from typeforge.analysis.model import ReturnCheckProvenance
from typeforge.compiler.pipeline import compile_source
from typeforge.compiler.source import ReturnSite, SourcePosition, SourceSpan
from typeforge.compiler.stub_ir import TypeName


def test_completed_plan_projects_guarded_return_without_compiler_work() -> None:
    source = dedent("""        from typeforge import Map
        def convert[T](value: T) -> Map[T, int : str, ... : bytes]:
            if type(value) is int:
                return value
            raise RuntimeError
        """)
    path = Path("convert.py")
    plan = compile_source(source, path, maximum_arity=1).unwrap()

    (obligation,) = plan.verification.obligations
    assert obligation.function is plan.source.functions[0]
    assert obligation.expected_types == (TypeName("str"),)
    assert obligation.narrowed_inputs == (TypeName("int"),)
    assert obligation.site == ReturnSite(
        statement=SourceSpan(path, SourcePosition(4, 8), SourcePosition(4, 20)),
        expression=SourceSpan(path, SourcePosition(4, 15), SourcePosition(4, 20)),
    )
    with (
        patch("ast.parse", side_effect=AssertionError("unexpected parse")),
        patch.object(Path, "read_text", side_effect=AssertionError("unexpected read")),
        patch(
            "typeforge.overlay.transform.compile_source",
            side_effect=AssertionError("unexpected compilation"),
        ),
        patch(
            "typeforge.compiler.pipeline._compilation.analyze_implementations",
            side_effect=AssertionError("unexpected analysis"),
        ),
        patch(
            "typeforge.compiler.pipeline._compilation.adapt_source_module",
            side_effect=AssertionError("unexpected adaptation"),
        ),
        patch(
            "typeforge.compiler.pipeline._compilation.lower_variadic_module",
            side_effect=AssertionError("unexpected specialization"),
        ),
    ):
        document = overlay.project_overlay(plan, version=7).unwrap()

    assert document.path == path
    assert document.version == 7
    assert document.authored_text == source
    assert document.generated_text == dedent(
        "        from typing import TYPE_CHECKING, overload  # "
        "typeforge: overlay-import\n"
        "        from typeforge import Map\n"
        "        if TYPE_CHECKING:  # typeforge: overlay\n"
        "            @overload\n"
        "            def convert(value: int) -> str: ...\n"
        "            @overload\n"
        "            def convert[T](value: T) -> str | bytes: "
        "...\n"
        "        # typeforge: overlay-end\n"
        "        def convert[T](value: T) -> str | bytes:\n"
        "            if type(value) is int:\n"
        "                __typeforge_return_1: str = value\n"
        "                return value\n"
        "            raise RuntimeError\n"
        "        "
    )
    (check,) = tuple(mapping for mapping in document.mappings if mapping.provenance)
    assert check.origin is MappingKind.GENERATED
    assert check.authored.start.line == 3
    assert check.authored.start.column == 15
    assert source[check.authored.start.offset : check.authored.end.offset] == "value"
    assert (
        document.generated_text[
            check.generated.start.offset : check.generated.end.offset
        ]
        == "__typeforge_return_1: str = value\n        "
    )
    assert check.provenance == ReturnCheckProvenance(
        callable_name=("convert",),
        return_annotation="Map[T, int : str, ... : bytes]",
        controller_parameter="value",
        narrowed_inputs=("int",),
        expected_types=("str",),
    )


def test_transformation_compiles_and_parses_the_authored_module_once() -> None:
    source = dedent("""        from typeforge import Map
        def convert[T](value: T) -> Map[T, int : str]:
            if type(value) is int:
                return value
            raise RuntimeError
        """)
    with (
        patch("ast.parse", wraps=ast.parse) as parse,
        patch(
            "typeforge.overlay.transform.compile_source", wraps=compile_source
        ) as compile,
    ):
        document = overlay.transform_source(source).unwrap()

    assert "__typeforge_return_1: str = value" in document.generated_text
    assert compile.call_count == 1
    module_parses = tuple(
        call
        for call in parse.call_args_list
        if call.kwargs.get("mode", "exec") == "exec"
    )
    assert len(module_parses) == 1
    assert module_parses[0].args == (source,)


def test_projection_uses_preamble_and_decorator_locations() -> None:
    preamble = dedent('''\
        """Documentation
        across lines."""
        from __future__ import (
            annotations,
        )
        ''')
    source = preamble + dedent("""\
        from typeforge import Collect, Each
        class First:
            @decorate(
                "first",
            )
            async def collect[T](*values: Each[T]) -> Collect[T]: ...
        if enabled:
            class Second:
                @decorate(
                    "second",
                )
                async def collect[T](*values: Each[T]) -> Collect[T]: ...
        """)
    plan = compile_source(source, Path("decorated.py"), maximum_arity=0).unwrap()

    with patch("ast.parse", side_effect=AssertionError("unexpected parse")):
        document = overlay.project_overlay(plan).unwrap()

    assert document.generated_text.startswith(
        preamble
        + "from typing import TYPE_CHECKING, overload  # typeforge: overlay-import\n"
    )
    blocks = tuple(
        mapping
        for mapping in document.mappings
        if mapping.origin is MappingKind.GENERATED
        and "if TYPE_CHECKING:"
        in document.generated_text[
            mapping.generated.start.offset : mapping.generated.end.offset
        ]
    )
    assert len(blocks) == 2
    for block, indentation in zip(blocks, ("    ", "        "), strict=True):
        emitted = document.generated_text[
            block.generated.start.offset : block.generated.end.offset
        ]
        assert emitted.startswith(f"{indentation}if TYPE_CHECKING:")
        assert "async def collect() -> tuple[()]: ..." in emitted
        assert document.generated_text[block.generated.end.offset :].startswith(
            f"{indentation}@decorate(\n"
        )
        assert source[block.authored.start.offset : block.authored.end.offset] == (
            "async def collect[T](*values: Each[T]) -> Collect[T]: ..."
        )
