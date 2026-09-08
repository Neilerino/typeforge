import ast
from dataclasses import fields, is_dataclass
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from typeforge.compiler.pipeline import compile_source
from typeforge.compiler.source import (
    ReturnSite,
    SourcePosition,
    SourceSpan,
    parse_source,
)


def test_compilation_retains_the_exact_snapshot_from_one_parse() -> None:
    source = dedent("""        raise RuntimeError("authored code must never execute")
        def choose[T](value: T) -> Map[T, int : str, ... : bytes]:
            return "café"
        """)
    path = Path("not-on-disk/snapshot.py")

    with (
        patch("ast.parse", wraps=ast.parse) as parse,
        patch.object(Path, "read_text", side_effect=AssertionError("unexpected read")),
    ):
        plan = compile_source(source, path=path, maximum_arity=2).unwrap()

    assert plan.source.text == source
    assert plan.source.path == path
    assert parse.call_count == 1
    assert parse.call_args.args == (source,)


def test_source_facts_locate_preamble_decorators_and_return_sites() -> None:
    source = dedent('''\
        """Module documentation
        spanning two lines."""
        from __future__ import (
            annotations,
        )
        class Outer:
            if enabled:
                @decorate(
                    "café",
                )
                async def choose(value: str) -> str:
                    if value: return "é"; value = "after"
                    return
        ''')
    path = Path("locations.py")

    plan = compile_source(source, path=path, maximum_arity=2).unwrap()
    facts = plan.source
    (function,) = facts.functions

    assert facts.docstring_span == span(path, 1, 0, 2, 22)
    assert facts.future_import_spans == (span(path, 3, 0, 5, 1),)
    assert function.qualified_name == ("Outer", "choose")
    assert function.span == span(path, 11, 8, 13, 18)
    assert function.decorator_spans == (span(path, 8, 9, 10, 9),)
    assert function.body_span == span(path, 12, 12, 13, 18)
    assert facts.return_sites == (
        ReturnSite(
            statement=span(path, 12, 22, 12, 33),
            expression=span(path, 12, 29, 12, 33),
        ),
        ReturnSite(statement=span(path, 13, 12, 13, 18), expression=None),
    )
    assert tuple(item.span for item in facts.identifiers if item.name == "value") == (
        span(path, 11, 25, 11, 35),
        span(path, 12, 15, 12, 20),
        span(path, 12, 35, 12, 40),
    )


def test_public_plan_contains_facts_but_no_python_syntax_nodes() -> None:
    source = """from typeforge import Map
def example[T](value: T) -> Map[T, int : str]:
    return value
"""
    parsed = parse_source(source, path=Path("example.py")).unwrap()
    plan = compile_source(source, path=Path("example.py"), maximum_arity=2).unwrap()

    assert isinstance(parsed.tree, ast.Module)
    assert parsed.source == plan.source
    assert plan.verification.obligations
    assert_no_ast(plan)


def span(
    path: Path, line: int, column: int, end_line: int, end_column: int
) -> SourceSpan:
    return SourceSpan(
        path=path,
        start=SourcePosition(line=line, column=column),
        end=SourcePosition(line=end_line, column=end_column),
    )


def assert_no_ast(value: object) -> None:
    assert not isinstance(value, ast.AST)
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            assert_no_ast(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            assert_no_ast(item)


def test_identifier_facts_include_unused_parameters_in_nested_scopes() -> None:
    source = dedent("""\
        def outer(unused: int) -> None:
            def nested(__typeforge_return_1): ...
            callback = lambda __typeforge_return_2: None
        """)
    path = Path("identifiers.py")

    facts = compile_source(source, path=path, maximum_arity=2).unwrap().source

    assert tuple(item.name for item in facts.identifiers) == (
        "unused",
        "int",
        "__typeforge_return_1",
        "callback",
        "__typeforge_return_2",
    )
    assert tuple(
        item.span for item in facts.identifiers if item.name.startswith("__")
    ) == (
        span(path, 2, 15, 2, 35),
        span(path, 3, 22, 3, 42),
    )
