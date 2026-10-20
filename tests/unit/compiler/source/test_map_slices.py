"""Production source normalization contracts for slice Map."""

from pathlib import Path

import pytest
from returns.result import Failure

from typeforge.compiler.pipeline import AdaptationError, compile_source, generate_module
from typeforge.compiler.source import (
    AppliedTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    SourceSyntaxError,
    UnionTypeExpression,
    parse_source,
)


def test_empty_output_normalizes_to_none_and_emits_the_same_interface(
    tmp_path: Path,
) -> None:
    source = """from typeforge import Map
from typeforge._markers import Case, Map as CanonicalMap
from typeforge.pydantic import Schema
"""
    path = tmp_path / "example.py"
    outputs: list[str] = []
    for expression in (
        "Map[int, int:]",
        "Map[int, int:None]",
        "CanonicalMap[int, Case[int, None]]",
    ):
        text = source + f"class Payload:\n    value: Schema[{expression}]\n"
        path.write_text(text)
        outputs.append(generate_module(path, maximum_arity=2).unwrap().content)

    assert outputs[0] == outputs[1] == outputs[2]
    assert "value: None" in outputs[0]
    parsed = parse_source(source + "type Selected = Map[int, int:]\n", path).unwrap()
    mapping = parsed.source.aliases[0].value
    assert isinstance(mapping, MarkerTypeExpression)
    branch = mapping.arguments[1]
    assert isinstance(branch, MarkerTypeExpression)
    assert branch.marker is MarkerKind.CASE
    assert branch.source == "int:"
    assert branch.arguments[1].source == "None"


@pytest.mark.parametrize(
    ("expression", "fragment", "message"),
    [
        ("Map[int, int:str:bytes]", "bytes", "step"),
        ("Map[int, ...:str, int:bytes]", "int:bytes", "fallback"),
        ("Map[int, ...:str, ...:bytes]", "...:bytes", "fallback"),
        (
            "Map[int, ...:str, bytes]",
            "bytes",
            "fallback",
        ),
        ('Map[str, "text": bytes]', '"text"', "Literal"),
        ('Map[str, All[Equal["text"]]: bytes]', '"text"', "Literal"),
        ("Map[int:str]", "int:str", "subject"),
    ],
)
def test_invalid_slice_syntax_returns_a_located_failure(
    expression: str,
    fragment: str,
    message: str,
) -> None:
    path = Path("authored.py")
    source = (
        "from typeforge import Map\n"
        "from typeforge._markers import All, Equal\n"
        f"type Selected = {expression}\n"
    )
    for result in (
        parse_source(source, path),
        compile_source(source, path, maximum_arity=2),
    ):
        assert isinstance(result, Failure)
        error = result.failure()
        assert isinstance(error, SourceSyntaxError)
        assert error.path == path
        assert message in error.message
        line = source.splitlines()[error.span.start.line - 1].encode()
        assert (
            line[error.span.start.column : error.span.end.column].decode() == fragment
        )


@pytest.mark.parametrize(
    ("sliced", "canonical", "expected"),
    [
        ("Map[None, :str]", "CanonicalMap[None, Case[None, str]]", "str"),
        ("Map[None, :]", "CanonicalMap[None, Case[None, None]]", "None"),
        ("Map[int, ...:]", "CanonicalMap[int, Default[None]]", "None"),
        ("Map[int, ...:None]", "CanonicalMap[int, Default[None]]", "None"),
        ("Map[int, int:str:None]", "CanonicalMap[int, Case[int, str]]", "str"),
        ("Map[int, ...:str:None]", "CanonicalMap[int, Default[str]]", "str"),
        (
            'Map[Literal["text"], Equal[Literal["text"]]: str]',
            (
                'CanonicalMap[Literal["text"], '
                'Case[Equal[Literal["text"], Literal["text"]], str]]'
            ),
            "str",
        ),
        (
            "Map[Literal[-1], -1: bytes]",
            "CanonicalMap[Literal[-1], Case[Literal[-1], bytes]]",
            "bytes",
        ),
        (
            "Map[Literal[True], True: str]",
            "CanonicalMap[Literal[True], Case[Literal[True], str]]",
            "str",
        ),
        (
            "Map[Literal[b'x'], b'x': bytes]",
            "CanonicalMap[Literal[b'x'], Case[Literal[b'x'], bytes]]",
            "bytes",
        ),
        (
            "Map[int, int:str, int:bytes]",
            "CanonicalMap[int, Case[int, str], Case[int, bytes]]",
            "str",
        ),
        ("Map[str, int:bytes]", "CanonicalMap[str, Case[int, bytes]]", "Never"),
        ("Map[int, int:Never]", "CanonicalMap[int, Case[int, Never]]", "Never"),
    ],
)
def test_source_spelling_preserves_canonical_interface(
    tmp_path: Path,
    sliced: str,
    canonical: str,
    expected: str,
) -> None:
    imports = """from typing import Literal, Never
from typeforge import Map
from typeforge._markers import Equal
from typeforge._markers import Case, Default, Map as CanonicalMap
from typeforge.pydantic import Schema
"""
    path = tmp_path / "example.py"
    outputs: list[str] = []
    for expression in (sliced, canonical):
        path.write_text(imports + f"class Payload:\n    value: Schema[{expression}]\n")
        outputs.append(generate_module(path, maximum_arity=2).unwrap().content)

    assert outputs[0] == outputs[1]
    assert f"value: {expected}" in outputs[0]


@pytest.mark.parametrize(
    ("imports", "mapping", "predicate"),
    [
        (
            "from typeforge._markers import Equal\nfrom typeforge import Map",
            "Map",
            "Equal",
        ),
        (
            "from typeforge._markers import Equal as Is\n"
            "from typeforge import Map as Select",
            "Select",
            "Is",
        ),
        ("import typeforge as tf", "tf.Map", "tf.Is"),
        ("import typeforge", "typeforge.Map", "typeforge.Is"),
    ],
)
def test_imported_map_and_predicates_normalize_to_existing_data(
    tmp_path: Path,
    imports: str,
    mapping: str,
    predicate: str,
) -> None:
    text = (
        f"{imports}\ntype Selected[T] = {mapping}[T, {predicate}[int]: str, ...: T]\n"
    )
    expression = parse_source(text).unwrap().source.aliases[0].value
    assert isinstance(expression, MarkerTypeExpression)
    assert expression.marker is MarkerKind.MAP
    subject, case, default = expression.arguments
    assert isinstance(case, MarkerTypeExpression)
    condition = case.arguments[0]
    assert isinstance(condition, MarkerTypeExpression)
    assert condition.marker is MarkerKind.EQUAL
    assert condition.arguments[0] is subject
    assert case.source == f"{predicate}[int]: str"
    assert isinstance(default, MarkerTypeExpression)
    assert default.marker is MarkerKind.DEFAULT
    path = tmp_path / "example.py"
    path.write_text(
        imports + f"\ndef select[T](value: T) -> {mapping}[T, int:str, ...:T]: ...\n"
    )
    assert (
        "def select(value: int) -> str"
        in generate_module(path, maximum_arity=2).unwrap().content
    )


@pytest.mark.parametrize("imports", ["", "from another_library import Map"])
def test_unrelated_subscriptions_keep_their_original_slices(imports: str) -> None:
    text = f'{imports}\ntype Selected = Map[int, "text": bytes: str]\n'
    expression = parse_source(text).unwrap().source.aliases[0].value
    assert isinstance(expression, AppliedTypeExpression)
    assert isinstance(expression.arguments[1], RawTypeExpression)
    assert expression.arguments[1].source == '"text": bytes: str'


def test_nested_subject_binding_and_union_roles_preserve_authored_spans() -> None:
    source = """from typeforge._markers import Equal
from typeforge import Map, Value
type Résultat[T] = Map[
    T | int,
    list[Value]: Map[Value, Equal[int | str]: tuple[Value | None, ...]],
    ...: bytes,
] | None
"""
    outer = parse_source(source).unwrap().source.aliases[0].value
    assert isinstance(outer, UnionTypeExpression)
    mapping = outer.members[0]
    assert isinstance(mapping, MarkerTypeExpression)
    assert isinstance(mapping.arguments[0], UnionTypeExpression)
    branch = mapping.arguments[1]
    assert isinstance(branch, MarkerTypeExpression)
    assert isinstance(branch.arguments[0], AppliedTypeExpression)
    nested = branch.arguments[1]
    assert isinstance(nested, MarkerTypeExpression)
    inner_branch = nested.arguments[1]
    assert isinstance(inner_branch, MarkerTypeExpression)
    predicate = inner_branch.arguments[0]
    assert isinstance(predicate, MarkerTypeExpression)
    assert predicate.arguments[0] is nested.arguments[0]
    assert isinstance(predicate.arguments[1], UnionTypeExpression)
    for node in (branch, branch.arguments[0], nested, inner_branch, predicate):
        line = source.splitlines()[node.span.start.line - 1].encode()
        assert (
            line[node.span.start.column : node.span.end.column].decode() == node.source
        )


def test_output_strings_keep_their_existing_type_position_meaning() -> None:
    source = 'from typeforge import Map\ntype Selected = Map[int, int: "Forward"]\n'
    expression = parse_source(source).unwrap().source.aliases[0].value
    assert isinstance(expression, MarkerTypeExpression)
    branch = expression.arguments[1]
    assert isinstance(branch, MarkerTypeExpression)
    assert isinstance(branch.arguments[0], NameTypeExpression)
    assert isinstance(branch.arguments[1], RawTypeExpression)
    assert branch.arguments[1].source == '"Forward"'


def test_unicode_failure_locations_use_authored_utf8_columns() -> None:
    source = 'from typeforge import Map\ntype Résultat = Map[str, "café": bytes]\n'
    result = parse_source(source)
    assert isinstance(result, Failure)
    error = result.failure()
    line = source.splitlines()[1].encode()
    assert line[error.span.start.column : error.span.end.column].decode() == '"café"'


@pytest.mark.parametrize(
    ("expression", "fragment", "message"),
    [
        ("Map[int]", "Map[int]", "at least one"),
        (
            "Map[int, Equal[int, str, bytes]: float]",
            "Equal[int, str, bytes]",
            "two type arguments",
        ),
    ],
)
def test_existing_normalization_owner_reports_arity_and_entry_errors(
    expression: str,
    fragment: str,
    message: str,
) -> None:
    source = (
        "from typeforge import Map\n"
        "from typeforge._markers import Equal\n"
        f"type Bad = {expression}\n"
    )
    result = compile_source(source, Path("authored.py"), maximum_arity=2)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, AdaptationError)
    assert error.expression == fragment
    assert message in error.message


def test_compiler_never_executes_authored_slice_expressions(tmp_path: Path) -> None:
    sentinel = tmp_path / "executed"
    source = (
        "from pathlib import Path\n"
        "from typeforge._markers import Assignable\nfrom typeforge import Map\n"
        f"Path({str(sentinel)!r}).touch()\n"
        "_tripwire: int = 1 // 0\n"
        "def select[T](value: T) -> Map[T, Assignable[int]:str, ...:None]: ...\n"
    )
    path = tmp_path / "isolated.py"
    path.write_text(source)
    assert (
        "def select(value: int) -> str"
        in generate_module(path, maximum_arity=2).unwrap().content
    )
    assert not sentinel.exists()
