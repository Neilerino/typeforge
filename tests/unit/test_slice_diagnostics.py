"""Diagnostics describe public branches rather than normalized marker data."""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

import pytest
from returns.result import Failure

from pydantic import PydanticSchemaGenerationError, TypeAdapter, ValidationError
from typeforge import Map
from typeforge.compiler.pipeline import AdaptationError, compile_source
from typeforge.compiler.source import SourceSyntaxError, parse_source
from typeforge.pydantic import Input, Schema
from typeforge.pydantic._errors import SchemaIssue


@pytest.mark.parametrize(
    ("expression", "message", "error_type"),
    [
        ("Map[int]", "a subject and at least one branch", AdaptationError),
        ("Map[int, int: str, bytes]", "selector: output", SourceSyntaxError),
    ],
)
def test_compiler_branch_errors_use_public_syntax(
    expression: str,
    message: str,
    error_type: type[AdaptationError | SourceSyntaxError],
) -> None:
    source = f"from typeforge import Map\ntype Invalid = {expression}\n"
    result = compile_source(source, Path("authored.py"), maximum_arity=2)

    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, error_type)
    assert message in error.message
    assert "Case" not in error.message
    assert "Default" not in error.message


@pytest.mark.parametrize(
    ("annotation", "code", "display"),
    [
        (Map[str, int:bytes], "map_no_match", "Map[str, int: bytes]"),
        (
            Map[Input, list[int] : str, ...:bytes],
            "unsupported_runtime_pattern",
            "Map[Input, list[int]: str, ...: bytes]",
        ),
        (
            Map[int, int : Map[str, bytes:float]],
            "map_no_match",
            "Map[str, bytes: float]",
        ),
    ],
)
def test_runtime_errors_render_slice_branches(
    annotation: object, code: str, display: str
) -> None:
    with pytest.raises(PydanticSchemaGenerationError) as failure:
        TypeAdapter[object](Schema[annotation])

    message = str(failure.value)
    assert f"[{code}]" in message
    assert display in message
    assert "Case[" not in message
    assert "Default[" not in message


def test_rendering_does_not_rewrite_literal_contents() -> None:
    annotation = Map[Literal["Case[int, str]"], int:bytes]
    with pytest.raises(PydanticSchemaGenerationError) as failure:
        TypeAdapter[object](Schema[annotation])

    assert "Map[Literal['Case[int, str]'], int: bytes]" in str(failure.value)


def test_deferred_no_match_uses_slice_display_and_preserves_field_location() -> None:
    adapter = TypeAdapter[object](list[Schema[Map[Input, int:int]]])
    with pytest.raises(ValidationError) as failure:
        adapter.validate_python(["wrong"])

    error = failure.value.errors()[0]
    assert error["type"] == "typeforge_map_no_match"
    assert error["loc"] == (0,)
    assert error["input"] == "wrong"
    assert "Map[Input, int: int]" in error["msg"]


@pytest.mark.parametrize(
    "expression",
    [
        'Map[int, int: list[Map[str, "café": bytes] | None]]',
        'Map[str | int, All[Equal["café"]]: bytes, ...: float]',
    ],
)
def test_errors_inside_union_branches_preserve_authored_utf8_spans(
    expression: str,
) -> None:
    source = f"from typeforge import All, Equal, Map\ntype Résultat = {expression}\n"
    path = Path("authored.py")
    for result in (parse_source(source, path), compile_source(source, path, 2)):
        assert isinstance(result, Failure)
        error = result.failure()
        assert isinstance(error, SourceSyntaxError)
        assert error.path == path
        assert 'Literal["text"]' in error.message
        line = source.splitlines()[error.span.start.line - 1].encode()
        assert (
            line[error.span.start.column : error.span.end.column].decode() == '"café"'
        )


def test_predicate_alias_failure_keeps_the_authored_literal_expression() -> None:
    source = """\
from typeforge import Equal, Map
type Text = Equal["café"]
type Result[T] = Map[T, Text: bytes, ...: str]
"""
    result = compile_source(source, Path("authored.py"), maximum_arity=2)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, AdaptationError)
    assert error.expression == '"café"'
    assert 'Literal["text"]' in error.message


def test_annotation_display_preserves_aliases_metadata_and_union_grouping() -> None:
    type Unresolved = MissingName  # noqa: F821 - alias body must not be evaluated

    expression = Annotated[
        list[Map[str, int : bytes | None]] | Unresolved,
        "Case[int, str]",
    ]
    rendered = SchemaIssue("test", "parsing", expression, "failure").render()
    assert (
        "Annotated[list[Map[str, int: bytes | None]] | Unresolved, 'Case[int, str]']"
        in rendered
    )


def test_display_traverses_callable_parameter_lists_without_rewriting_metadata() -> (
    None
):
    expression = Annotated[
        Callable[[Map[str, int:bytes]], int],
        ["Case[int, str]"],
    ]
    rendered = SchemaIssue("test", "parsing", expression, "failure").render()
    assert "Callable[[Map[str, int: bytes]], int]" in rendered
    assert "['Case[int, str]']" in rendered
