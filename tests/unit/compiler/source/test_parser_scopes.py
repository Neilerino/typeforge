from pathlib import Path

import pytest
from returns.result import Failure

from typeforge.compiler.source import (
    AppliedTypeExpression,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    parse_source,
)


def test_lexical_names_shadow_imports_and_captures_without_leaking() -> None:
    module = (
        parse_source(
            "from typeforge import Capture, Map, type_function\n"
            "T = Capture('outer')\n"
            "@type_function\n"
            "def Selected[T]():\n"
            "    type Map[T] = tuple[T, T]\n"
            "    return Map[T]\n"
            "@type_function\n"
            "def Independent[T]():\n"
            "    type Map[T] = list[T]\n"
            "    return Map[T]\n"
            "type Outside = Map[int, int: str]\n"
        )
        .unwrap()
        .source
    )
    outside, selected, independent = module.aliases
    assert isinstance(outside.value, MarkerTypeExpression)
    assert module.captures[0][1].name == "outer"

    for declaration in (selected, independent):
        local = declaration.local_aliases[0]
        assert local.qualified_name == (declaration.name, "Map")
        assert isinstance(local.value, AppliedTypeExpression)
        for argument in local.value.arguments:
            assert isinstance(argument, NameTypeExpression)
            assert argument.qualified_name == (declaration.name, "Map", "T")

        assert isinstance(declaration.value, AppliedTypeExpression)
        assert isinstance(declaration.value.constructor, NameTypeExpression)
        assert declaration.value.constructor.qualified_name == (
            declaration.name,
            "Map",
        )
        argument = declaration.value.arguments[0]
        assert isinstance(argument, NameTypeExpression)
        assert argument.qualified_name == (declaration.name, "T")


def test_missing_annotation_is_distinct_from_authored_none() -> None:
    module = (
        parse_source(
            "def unannotated(value): ...\n"
            "def annotated(value: None) -> None: ...\n"
            "type Nothing = None\n"
        )
        .unwrap()
        .source
    )
    unannotated, annotated = module.functions
    assert unannotated.parameters[0].annotation is None
    assert unannotated.returns is None
    assert isinstance(annotated.parameters[0].annotation, RawTypeExpression)
    assert isinstance(annotated.returns, RawTypeExpression)
    assert isinstance(module.aliases[0].value, RawTypeExpression)
    assert annotated.returns.source == module.aliases[0].value.source == "None"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("type Local[T: int] = T", "local aliases require unconstrained"),
        ("type Local = int\n    type Local = str", "is declared more than once"),
        ("value = side_effect()", "supports capture declarations and local aliases"),
    ],
)
def test_construction_failures_cross_the_source_boundary_with_authored_spans(
    body: str, message: str
) -> None:
    source = (
        "from typeforge import type_function\n"
        "@type_function\n"
        "def Selected():\n"
        f"    {body}\n"
        "    return int\n"
    )
    path = Path("authored.py")
    result = parse_source(source, path)
    assert isinstance(result, Failure)
    error = result.failure()
    assert message in error.message
    assert error.path == error.span.path == path
    assert error.span.start.line == 3 + len(body.splitlines())
    assert error.span.start.column == 4
