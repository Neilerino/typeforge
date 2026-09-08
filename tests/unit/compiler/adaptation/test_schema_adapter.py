from pathlib import Path

import pytest
from returns.result import Failure, Result, Success

from typeforge.compiler.adaptation import AdaptationError, adapt_schema_expression
from typeforge.compiler.semantic_adapter import (
    CompilerTypeSystem,
    NamedType,
    StaticType,
)
from typeforge.compiler.source import (
    SchemaTypeExpression,
    SourceModule,
    SourceSpan,
    parse_source,
)
from typeforge.compiler.stub_ir import (
    GeneratedElementOrigin,
    TypeApplication,
    TypeName,
    UnionExpression,
    UnpackedType,
)
from typeforge.semantics import (
    RecordFamily,
    RecordShape,
    SemanticAdapterError,
    SemanticIssue,
)


def schema_source(
    expression: str, aliases: str = ""
) -> tuple[SourceModule, SchemaTypeExpression]:
    source = (
        parse_source(
            "from typeforge import Map, Value, Equal, Assignable\n"
            "from typeforge import All, Any, Not, MapFields, Field, Key\n"
            "from typeforge.pydantic import Input, Schema\n"
            f"{aliases}\n"
            f"type Selected = Schema[{expression}]\n",
            Path("schema.py"),
        )
        .unwrap()
        .source
    )
    boundary = source.aliases[-1].value
    assert isinstance(boundary, SchemaTypeExpression)
    return source, boundary


def test_schema_adapter_evaluates_aliased_structural_outputs() -> None:
    source, boundary = schema_source(
        "Outer[list[int]]",
        """type Inner[T] = Map[T, list[Value] : set[Value] | None]
type Outer[T] = Map[T, list[Value] : Inner[T]]""",
    )

    assert adapt_schema_expression(
        boundary, source.aliases, declaration="Selected"
    ) == Success(
        UnionExpression(
            (TypeApplication(TypeName("set"), (TypeName("int"),)), TypeName("None"))
        )
    )


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("Map[T, Equal[T, T] : str, ... : bytes]", TypeName("str")),
        (
            "Map[T, Equal[T, int] : str, T : bytes, ... : float]",
            UnionExpression((TypeName("str"), TypeName("bytes"))),
        ),
        (
            "Map[tuple[int, T], tuple[str, int] : str, ... : bytes]",
            TypeName("bytes"),
        ),
        (
            "Map[list[T], list[Value] : set[Value]]",
            TypeApplication(TypeName("set"), (TypeName("T"),)),
        ),
    ],
)
def test_schema_adapter_preserves_unresolved_generic_identity(
    expression: str, expected: object
) -> None:
    source, boundary = schema_source(expression)
    assert adapt_schema_expression(
        boundary, source.aliases, declaration="Selected", type_parameters=("T",)
    ) == Success(expected)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (
            "Map[Input, int : Map[Input, int : str, ... : float], ... : bytes]",
            UnionExpression((TypeName("str"), TypeName("float"), TypeName("bytes"))),
        ),
        (
            "list[Map[int, int : str]]",
            TypeApplication(TypeName("list"), (TypeName("str"),)),
        ),
        (
            "Map[int, int : list[Map[int, int : str]]]",
            TypeApplication(TypeName("list"), (TypeName("str"),)),
        ),
        (
            "Map[int, int : tuple[Map[Input, int : str]]]",
            TypeApplication(TypeName("tuple"), (TypeName("str"),)),
        ),
        ("Schema[Map[int, int : str]]", TypeName("str")),
        ("Map[int, int : Schema[str]]", TypeName("str")),
        (
            "tuple[*Map[int, int : tuple[str, bytes]]]",
            TypeApplication(
                TypeName("tuple"),
                (
                    UnpackedType(
                        TypeApplication(
                            TypeName("tuple"), (TypeName("str"), TypeName("bytes"))
                        )
                    ),
                ),
            ),
        ),
        ("Map[Input, int : str, ... : Never]", TypeName("str")),
    ],
)
def test_schema_adapter_composes_nested_types(
    expression: str, expected: object
) -> None:
    source, boundary = schema_source(expression)
    assert adapt_schema_expression(
        boundary, source.aliases, declaration="Selected"
    ) == Success(expected)


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("Equal[int]", "Equal requires two type arguments"),
        ("Input", "Input requires value-time evaluation"),
        ("Value", "Value requires MapFields or a structural Map case"),
        ("Equal[int, int]", "Schema must evaluate to a type"),
        (
            "MapFields[int, Field[Key, Value]]",
            "MapFields requires a supported record type",
        ),
        ("Map[int, int : Equal[int, int]]", "Schema must evaluate to a type"),
    ],
)
def test_schema_failures_use_authored_diagnostics(
    expression: str, message: str
) -> None:
    source, boundary = schema_source(expression)
    assert adapt_schema_expression(
        boundary, source.aliases, declaration="Selected"
    ) == Failure(AdaptationError("Selected", boundary.source, message))


def test_equal_alias_results_keep_distinct_schema_roots_and_authored_origins() -> None:
    source, boundary = schema_source(
        "tuple[Schema[Alias[int]], Schema[Alias[int]]]",
        "type Alias[T] = Map[T, int : str]",
    )
    origins: list[GeneratedElementOrigin[SourceSpan]] = []
    first = adapt_schema_expression(
        boundary, source.aliases, declaration="Selected", origins=origins
    ).unwrap()
    second = adapt_schema_expression(
        boundary, source.aliases, declaration="Selected"
    ).unwrap()

    assert first == second
    assert first is not second
    assert isinstance(first, TypeApplication)
    assert first.arguments[0] == first.arguments[1] == TypeName("str")
    assert first.arguments[0] is not first.arguments[1]
    assert origins[-1].origin == boundary.span
    assert origins[-1].generated is first
    assert len(origins) == 3
    assert origins[0].origin != origins[1].origin
    assert origins[0].generated is first.arguments[0]
    assert origins[1].generated is first.arguments[1]


def test_failed_schema_adaptation_does_not_publish_partial_origins() -> None:
    source, boundary = schema_source("tuple[Schema[int], Schema[Input]]")
    origins: list[GeneratedElementOrigin[SourceSpan]] = []

    result = adapt_schema_expression(
        boundary, source.aliases, declaration="Selected", origins=origins
    )
    assert isinstance(result, Failure)
    assert origins == []


def test_schema_adapter_emits_supplied_record_references() -> None:
    source, boundary = schema_source("Map[Input, int : Payload, ... : list[Payload]]")
    payload = RecordShape[StaticType](
        family=RecordFamily.TYPED_DICT, name="Payload", fields=()
    )

    assert adapt_schema_expression(
        boundary,
        source.aliases,
        declaration="Selected",
        environment=(("Payload", payload),),
    ) == Success(
        UnionExpression(
            (
                TypeName("Payload"),
                TypeApplication(TypeName("list"), (TypeName("Payload"),)),
            )
        )
    )


def test_modeled_backend_failures_cross_the_authored_conversion_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = SemanticAdapterError("cannot compare authored types")
    calls: list[tuple[StaticType, StaticType]] = []

    def equal(
        self: CompilerTypeSystem, left: StaticType, right: StaticType
    ) -> Result[bool, SemanticIssue]:
        calls.append((left, right))
        return Failure(issue)

    monkeypatch.setattr(CompilerTypeSystem, "equal", equal)
    source, boundary = schema_source(
        "Map[int, Equal[int, str] : str, Equal[bytes, float] : bytes]"
    )

    assert adapt_schema_expression(
        boundary, source.aliases, declaration="Selected"
    ) == Failure(AdaptationError("Selected", boundary.source, issue.message))
    assert calls == [(NamedType("int"), NamedType("str"))]


def test_unexpected_backend_failures_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = RuntimeError("unexpected backend failure")

    def equal(
        self: CompilerTypeSystem, left: StaticType, right: StaticType
    ) -> Result[bool, SemanticIssue]:
        raise failure

    monkeypatch.setattr(CompilerTypeSystem, "equal", equal)
    source, boundary = schema_source("Map[int, int : str]")

    with pytest.raises(RuntimeError) as caught:
        adapt_schema_expression(boundary, source.aliases, declaration="Selected")

    assert caught.value is failure


def test_aliased_failures_report_the_authored_use_site() -> None:
    source, boundary = schema_source(
        "Broken[int]", "type Broken[T] = Map[T, Value : Value] | Input"
    )

    assert adapt_schema_expression(
        boundary, source.aliases, declaration="Selected"
    ) == Failure(
        AdaptationError(
            "Selected", boundary.source, "Input requires value-time evaluation"
        )
    )


@pytest.mark.parametrize(
    "expression",
    [
        "Schema[int | str] | bytes",
        "list[Schema[int]] | list[Schema[int]]",
    ],
)
def test_union_normalization_preserves_inner_schema_origins(expression: str) -> None:
    source, boundary = schema_source(expression)
    origins: list[GeneratedElementOrigin[SourceSpan]] = []
    output = adapt_schema_expression(
        boundary, source.aliases, declaration="Selected", origins=origins
    ).unwrap()

    assert len(origins) == 3
    assert origins[-1].generated is output
    if isinstance(output, UnionExpression):
        assert origins[0].generated is output.members[0]
        assert origins[1].generated is output.members[1]
        assert origins[0].origin == origins[1].origin
    else:
        assert isinstance(output, TypeApplication)
        assert origins[0].generated is output.arguments[0]
        assert origins[1].generated is output.arguments[0]
        assert origins[0].origin != origins[1].origin


def test_input_nested_in_a_selected_type_still_requires_value_time_binding() -> None:
    source, boundary = schema_source("Map[int, int : tuple[Input]]")

    assert adapt_schema_expression(
        boundary, source.aliases, declaration="Selected"
    ) == Failure(
        AdaptationError(
            "Selected", boundary.source, "Input requires value-time evaluation"
        )
    )
