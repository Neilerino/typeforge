from pathlib import Path

from returns.result import Failure, Success

from typeforge.compiler.frontend import (
    SourceReadError,
    SourceSyntaxError,
    parse_module,
    parse_source,
)
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    ParameterKind,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    StarredTypeExpression,
    TypeParameterKind,
    UnionTypeExpression,
    contains_marker,
    enriched_functions,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_module_finds_enriched_functions_and_preserves_spans() -> None:
    path = FIXTURES / "enriched.py"
    result = parse_module(path)

    assert isinstance(result, Success)
    module = result.unwrap()
    assert tuple(function.qualified_name for function in module.functions) == (
        ("combine",),
        ("Factory", "create"),
        ("ordinary",),
    )
    assert tuple(function.name for function in enriched_functions(module)) == (
        "combine",
        "create",
    )

    combine = module.functions[0]
    assert combine.span.start.line == 10
    assert combine.span.end.line == 17
    assert combine.type_parameters[0].kind is TypeParameterKind.TYPE_VAR
    assert tuple(parameter.kind for parameter in combine.parameters) == (
        ParameterKind.POSITIONAL_ONLY,
        ParameterKind.VAR_POSITIONAL,
        ParameterKind.KEYWORD_ONLY,
        ParameterKind.VAR_KEYWORD,
    )
    parsers = combine.parameters[1].annotation
    assert isinstance(parsers, MarkerTypeExpression)
    assert parsers.marker is MarkerKind.EACH
    assert parsers.source == "Each[Parser[T]]"
    assert parsers.span.start.line == 13
    returns = combine.returns
    assert returns is not None
    assert returns.source == "Parser[Gather[T]]"


def test_module_aliases_resolve_to_markers() -> None:
    result = parse_module(FIXTURES / "enriched.py")

    assert isinstance(result, Success)
    create = result.unwrap().functions[1]
    values = create.parameters[1].annotation
    assert isinstance(values, MarkerTypeExpression)
    assert values.marker is MarkerKind.EACH
    returns = create.returns
    assert isinstance(returns, MarkerTypeExpression)
    assert returns.marker is MarkerKind.COLLECT
    assert create.is_async


def test_unimported_marker_names_are_not_treated_as_typeforge_markers() -> None:
    result = parse_source("def f[T](value: Each[T]) -> Collect[T]: ...\n")

    assert isinstance(result, Success)
    assert enriched_functions(result.unwrap()) == ()


def test_pydantic_input_is_distinct_from_an_unrelated_input_type() -> None:
    result = parse_source(
        "from typeforge.pydantic import Input\n"
        "type Runtime = Input\n"
        "type Ordinary = other.Input\n"
    )

    assert isinstance(result, Success)
    runtime, ordinary = result.unwrap().aliases
    assert isinstance(runtime.value, RuntimeInputTypeExpression)
    assert not isinstance(ordinary.value, RuntimeInputTypeExpression)


def test_parses_markers_inside_unpacked_tuple_union() -> None:
    result = parse_source(
        "from typeforge import Collect\n"
        "def query[E, *Ts]() -> tuple[E, *Collect[Ts]] | None: ...\n"
    )

    assert isinstance(result, Success)
    returns = result.unwrap().functions[0].returns
    assert isinstance(returns, UnionTypeExpression)
    tuple_type = returns.members[0]
    assert isinstance(tuple_type, AppliedTypeExpression)
    unpacked = tuple_type.arguments[1]
    assert isinstance(unpacked, StarredTypeExpression)
    assert isinstance(unpacked.item, MarkerTypeExpression)
    assert unpacked.item.marker is MarkerKind.COLLECT
    assert contains_marker(returns, MarkerKind.COLLECT)


def test_syntax_failures_are_typed_and_located() -> None:
    result = parse_source("def broken(: ...\n")

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), SourceSyntaxError)
    assert result.failure().span.start.line == 1


def test_read_failures_are_typed() -> None:
    path = FIXTURES / "missing.py"
    result = parse_module(path)

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), SourceReadError)
    assert result.failure().path == path


def test_annotated_metadata_is_transparent_to_the_compiler_frontend() -> None:
    sources = (
        "from typing import Annotated\n"
        "from typeforge import Doc, Field, Key, MapFields, Value\n"
        "type Copy[T] = Annotated[\n"
        "    MapFields[T, Field[Key, Value]],\n"
        '    "custom metadata",\n'
        '    Doc("Copies every field."),\n'
        "]\n",
        "import typing_extensions as te\n"
        "from typeforge import Field, Key, MapFields, Value\n"
        "type Copy[T] = te.Annotated[\n"
        "    MapFields[T, Field[Key, Value]],\n"
        '    "custom metadata",\n'
        "]\n",
    )

    for source in sources:
        result = parse_source(source)

        assert isinstance(result, Success)
        alias = result.unwrap().aliases[0]
        assert isinstance(alias.value, MarkerTypeExpression)
        assert alias.value.marker is MarkerKind.MAP_FIELDS


def test_annotated_typed_dict_field_preserves_field_qualifiers() -> None:
    result = parse_source(
        "from typing import Annotated, NotRequired, ReadOnly, TypedDict\n"
        "from typeforge import Doc\n"
        "class Record(TypedDict):\n"
        '    value: Annotated[ReadOnly[NotRequired[int]], Doc("A value.")]\n'
    )

    assert isinstance(result, Success)
    field = result.unwrap().typed_dicts[0].fields[0]
    assert not field.required
    assert field.readonly
    assert field.annotation.source == "int"


def test_full_typeforge_syntax_is_recognized_in_type_aliases() -> None:
    result = parse_module(FIXTURES / "full_syntax.py")

    assert isinstance(result, Success)
    module = result.unwrap()
    assert tuple(alias.name for alias in module.aliases) == (
        "JsonValue",
        "PublicRecord",
        "EveryValue",
        "OptionalRecord",
        "FrozenRecord",
    )
    found_markers = {
        marker
        for marker in MarkerKind
        if any(contains_marker(alias.value, marker) for alias in module.aliases)
    }
    assert found_markers == set(MarkerKind) - {
        MarkerKind.EACH,
        MarkerKind.COLLECT,
    }
    assert module.aliases[0].type_parameters[0].name == "T"
    assert module.aliases[0].span.start.line == 24


def test_typed_dict_fields_preserve_shape_modifiers() -> None:
    result = parse_module(FIXTURES / "full_syntax.py")

    assert isinstance(result, Success)
    typed_dict = result.unwrap().typed_dicts[0]
    assert typed_dict.name == "Payload"
    assert not typed_dict.total
    assert tuple(
        (field.name, field.annotation.source, field.required, field.readonly)
        for field in typed_dict.fields
    ) == (
        ("identifier", "int", True, False),
        ("note", "str", False, False),
        ("token", "bytes", False, True),
        ("retries", "int", False, False),
        ("owner", "str", False, True),
    )
    assert typed_dict.fields[0].span.start.line == 53
    derived = result.unwrap().typed_dicts[1]
    assert derived.name == "ExtendedPayload"
    assert derived.bases == (("Payload",),)
    assert derived.fields[0].required


def test_ordinary_classes_preserve_generic_structure_and_members() -> None:
    result = parse_source(
        "from dataclasses import dataclass\n"
        "from typing import Protocol\n"
        "class Entity(Protocol):\n"
        "    def __hash__(self) -> int: ...\n"
        "@dataclass(frozen=True)\n"
        "class World[E: Entity]:\n"
        "    entities: set[E]\n"
        "    @classmethod\n"
        "    def empty(cls) -> World[E]: ...\n"
    )

    assert isinstance(result, Success)
    entity, world = result.unwrap().classes
    assert entity.bases[0].source == "Protocol"
    assert entity.methods[0].qualified_name == ("Entity", "__hash__")
    assert world.type_parameters[0].declaration == "E: Entity"
    assert world.decorators == ("dataclass(frozen=True)",)
    assert world.fields[0].annotation.source == "set[E]"
    assert world.methods[0].decorators == ("classmethod",)


def test_qualified_pydantic_schema_is_a_distinct_source_boundary() -> None:
    result = parse_source(
        "from typeforge.pydantic import Schema as RuntimeSchema\n"
        "from typeforge import Case, Default, Equal, Map\n"
        "class Model:\n"
        "    value: RuntimeSchema[Map["
        "int, Case[Equal[int, int], str], Default[bytes]]]\n"
        "    ordinary: Schema[int]\n"
    )

    assert isinstance(result, Success)
    value, ordinary = result.unwrap().classes[0].fields
    assert isinstance(value.annotation, SchemaTypeExpression)
    assert value.annotation.source.startswith("RuntimeSchema[")
    assert contains_marker(value.annotation, MarkerKind.MAP)
    assert isinstance(ordinary.annotation, AppliedTypeExpression)
