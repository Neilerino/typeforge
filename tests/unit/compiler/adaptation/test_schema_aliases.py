from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from returns.result import Failure

from tests.unit.compiler.semantic_adapter.test_semantic_lowering import (
    SPAN,
    application,
    name,
)
from typeforge.compiler.adaptation import AdaptationError, expand_schema_aliases
from typeforge.compiler.source import (
    AppliedTypeExpression,
    MapMarker,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
    normalize_marker,
    parse_source,
)


@pytest.mark.parametrize("use", ["Alias", "Alias[int, str]"])
def test_alias_arity_errors_are_modeled(use: str) -> None:
    source = (
        parse_source(f"type Alias[T] = T\ntype Selected = {use}\n", Path("aliases.py"))
        .unwrap()
        .source
    )

    assert expand_schema_aliases(
        source.aliases[-1].value, source.aliases, declaration="Selected"
    ) == Failure(
        AdaptationError(
            "Selected",
            use,
            "schema alias Alias requires 1 type argument; received 0"
            if use == "Alias"
            else "schema alias Alias requires 1 type argument; received 2",
        )
    )


WRAPPERS: tuple[Callable[[SourceTypeExpression], SourceTypeExpression], ...] = (
    lambda item: item,
    lambda item: AppliedTypeExpression("list[T]", SPAN, name("list"), (item,)),
    lambda item: AppliedTypeExpression("T[int]", SPAN, item, (name("int"),)),
    lambda item: UnionTypeExpression("T | None", SPAN, (item, name("None"))),
    lambda item: StarredTypeExpression("*T", SPAN, item),
    lambda item: SchemaTypeExpression("Schema[T]", SPAN, (item,)),
)


@pytest.mark.parametrize("wrap", WRAPPERS)
def test_substitution_and_expansion_visit_composite_source_positions(
    wrap: Callable[[SourceTypeExpression], SourceTypeExpression],
) -> None:
    source = parse_source("type Alias[T] = T\n", Path("aliases.py")).unwrap().source
    alias = replace(source.aliases[0], value=wrap(name("T")))

    assert expand_schema_aliases(
        application("Alias", name("bytes")), (alias,), declaration="Selected"
    ).unwrap() == wrap(name("bytes"))
    assert expand_schema_aliases(
        wrap(application("Alias", name("bytes"))),
        source.aliases,
        declaration="Selected",
    ).unwrap() == wrap(name("bytes"))


@pytest.mark.parametrize(
    "leaf",
    [
        name("bytes"),
        RawTypeExpression("'token'", SPAN),
        RuntimeInputTypeExpression("Input", SPAN),
    ],
)
def test_leaf_source_facts_remain_unchanged(leaf: SourceTypeExpression) -> None:
    assert expand_schema_aliases(leaf, (), declaration="Selected").unwrap() is leaf


@pytest.mark.parametrize("default", ["", ", ...: Never"])
def test_authored_defaults_survive_alias_expansion(default: str) -> None:
    source = (
        parse_source(
            "from typeforge import Map\n"
            "from typeforge.pydantic import Input\n"
            f"type Alias[T] = Map[Input, int: T{default}]\n"
            "type Selected = Alias[str]\n",
            Path("aliases.py"),
        )
        .unwrap()
        .source
    )
    expanded = expand_schema_aliases(
        source.aliases[-1].value, source.aliases, declaration="Selected"
    ).unwrap()

    assert isinstance(expanded, MarkerTypeExpression)
    assert expanded.span == source.aliases[0].value.span
    assert expanded.source == source.aliases[0].value.source
    assert len(expanded.arguments) == (3 if default else 2)
    if default:
        explicit_default = expanded.arguments[-1]
        assert isinstance(explicit_default, MarkerTypeExpression)
        assert explicit_default.arguments[0].source == "Never"


def test_nested_aliases_bind_arguments_before_semantic_lowering() -> None:
    source = (
        parse_source(
            """from typeforge import Map
type Inner[T] = Map[T, int : str, ... : bytes]
type Outer[T] = Map[T, int : Inner[T]]
type Selected = Outer[int]
""",
            Path("aliases.py"),
        )
        .unwrap()
        .source
    )

    expanded = expand_schema_aliases(
        source.aliases[-1].value, source.aliases, declaration="Selected"
    ).unwrap()

    assert isinstance(expanded, MarkerTypeExpression)
    outer = normalize_marker(expanded)
    assert isinstance(outer, MapMarker)
    assert isinstance(outer.subject, NameTypeExpression)
    assert outer.subject.source == "int"
    inner_expression = outer.entries[0].output
    assert isinstance(inner_expression, MarkerTypeExpression)
    inner = normalize_marker(inner_expression)
    assert isinstance(inner, MapMarker)
    assert isinstance(inner.subject, NameTypeExpression)
    assert inner.subject.source == "int"


@pytest.mark.parametrize(
    ("definition", "use", "cycle"),
    [
        ("type Loop[T] = Loop[T]", "Loop[int]", "Loop -> Loop"),
        (
            "type First[T] = Second[T]\ntype Second[T] = First[T]",
            "First[int]",
            "First -> Second -> First",
        ),
    ],
)
def test_alias_cycles_are_authored_failures(
    definition: str, use: str, cycle: str
) -> None:
    source = (
        parse_source(f"{definition}\ntype Selected = {use}\n", Path("aliases.py"))
        .unwrap()
        .source
    )

    assert expand_schema_aliases(
        source.aliases[-1].value, source.aliases, declaration="Selected"
    ) == Failure(AdaptationError("Selected", use, f"cyclic schema alias: {cycle}"))


@pytest.mark.parametrize("parameter", ["*Ts", "**P"])
def test_variadic_alias_binding_is_explicitly_unsupported(parameter: str) -> None:
    source = (
        parse_source(
            f"type Alias[{parameter}] = int\ntype Selected = Alias[str]\n",
            Path("aliases.py"),
        )
        .unwrap()
        .source
    )

    assert expand_schema_aliases(
        source.aliases[-1].value, source.aliases, declaration="Selected"
    ) == Failure(
        AdaptationError(
            "Selected",
            "Alias[str]",
            "schema alias Alias requires ordinary type parameters",
        )
    )


def test_repeated_finite_alias_application_is_not_a_cycle() -> None:
    source = (
        parse_source(
            "type Alias[T] = T\ntype Selected = Alias[Alias[int]]\n", Path("aliases.py")
        )
        .unwrap()
        .source
    )
    expanded = expand_schema_aliases(
        source.aliases[-1].value, source.aliases, declaration="Selected"
    ).unwrap()

    assert isinstance(expanded, NameTypeExpression)
    assert expanded.source == "int"
