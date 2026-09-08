import ast
from pathlib import Path
from textwrap import dedent

from pytest import MonkeyPatch, mark
from returns.result import Failure

from typeforge.analysis import MappingKind
from typeforge.compiler.pipeline import (
    AdaptationError,
    _compilation,
    compile_source,
    generate_module,
)
from typeforge.compiler.source import SourceModule
from typeforge.compiler.stub_ir import (
    MapType,
    OverloadDeclaration,
    TypeAliasDeclaration,
    TypeApplication,
    TypeName,
    TypeVariable,
    walk_module,
)
from typeforge.overlay import OverlayError, OverlayErrorCode, transform_source


def test_same_named_relationship_aliases_preserve_first_binding_projection() -> None:
    source = dedent("""\
        from typeforge import Case, Default, Map
        type Selected[T] = Map[T, Case[int, bytes], Default[str]]
        type Selected[T] = Map[T, Case[int, float], Default[None]]
        type Selected[T] = T
        """)

    plan = compile_source(source, Path("aliases.py"), maximum_arity=1).unwrap()

    assert all(
        origin.origin != plan.source.aliases[2].span for origin in plan.module.origins
    )
    document = transform_source(source, Path("aliases.py")).unwrap()

    assert document.generated_text == dedent("""\
        from typeforge import Case, Default, Map
        type Selected[T] = bytes | str
        type Selected[T] = bytes | str
        type Selected[T] = T
        """)


def test_reusable_relationships_preserve_alias_names_and_schema_branches() -> None:
    source = dedent("""\
        from typing import TypedDict
        from typeforge import Case, Default, Field, Key, Map, MapFields, Value
        from typeforge.pydantic import Schema
        class Payload(TypedDict):
            value: int
        type Copy[T] = MapFields[T, Field[Key, Value]]
        type Wire[T] = Map[T, Case[int, bytes], Default[str]]
        type Named[T] = Map[T, Case[int, Wire[T]], Default[None]]
        type Record[T] = Map[T, Case[int, Copy[Payload]], Default[None]]
        type Explicit[T] = Map[T, Case[int, Copy_Payload], Default[None]]
        type Wrapped[T] = Schema[Map[T, Case[int, bytes], Default[str]]]
        """)

    plan = compile_source(source, Path("relationships.py"), maximum_arity=1).unwrap()

    assert len(plan.module.reusable_elements) == 5
    wire, named, record, explicit, wrapped = plan.module.reusable_elements
    for expression in (wire, named, record, explicit, wrapped):
        assert isinstance(expression, MapType)

    assert isinstance(named, MapType)
    assert named.cases[0].output_type == TypeApplication(
        TypeName("Wire"), (TypeVariable("T"),)
    )
    assert isinstance(record, MapType)
    assert record.cases[0].output_type == TypeApplication(
        TypeName("Copy"), (TypeName("Payload"),)
    )
    assert isinstance(explicit, MapType)
    assert explicit.cases[0].output_type == TypeName("Copy_Payload")
    assert wrapped == wire
    for authored, expression in zip(
        plan.source.aliases[1:], plan.module.reusable_elements, strict=True
    ):
        assert any(
            origin.origin == authored.span and origin.generated is expression
            for origin in plan.module.origins
        )

    current = tuple(walk_module(plan.module))
    assert all(
        any(origin.generated is element for element in current)
        for origin in plan.module.origins
    )
    document = transform_source(source, Path("relationships.py")).unwrap()
    expected = source
    for authored, projected in (
        ("MapFields[T, Field[Key, Value]]", "object"),
        ("Schema[Map[T, Case[int, bytes], Default[str]]]", "bytes | str"),
        ("Map[T, Case[int, bytes], Default[str]]", "bytes | str"),
        ("Map[T, Case[int, Wire[T]], Default[None]]", "Wire[T] | None"),
        ("Map[T, Case[int, Copy[Payload]], Default[None]]", "Copy[Payload] | None"),
        ("Map[T, Case[int, Copy_Payload], Default[None]]", "Copy_Payload | None"),
    ):
        expected = expected.replace(authored, projected)

    assert document.generated_text == expected


@mark.parametrize(
    ("authored_value", "projected_value"),
    (
        ("Each[T]", "T"),
        ("Collect[T]", "tuple[T, ...]"),
        ("MapFields[T, Field[Key, Value]]", "object"),
        ("Schema[int]", "int"),
        ("list[Schema[int]]", "list[int]"),
        ("Map[T, Case[int, bytes], Default[str]]", "bytes | str"),
        ("Schema[Map[T, Case[int, bytes], Default[str]]]", "bytes | str"),
    ),
    ids=(
        "each-fallback",
        "collect-fallback",
        "record-fallback",
        "schema",
        "nested-schema",
        "relationship-union",
        "schema-relationship-union",
    ),
)
def test_alias_projection_uses_current_alias_origins_and_preserves_source_mapping(
    authored_value: str, projected_value: str
) -> None:
    source = dedent(f"""\
        from typeforge import Case, Collect, Default, Each, Field, Key
        from typeforge import Map, MapFields, Value
        from typeforge.pydantic import Schema

        type Ordinary = str
        type Selected[T] = {authored_value}
        type Reference[T] = Selected[T]
        """)
    path = Path("aliases.py")

    plan = compile_source(source, path, maximum_arity=1).unwrap()

    alias_origins = tuple(
        origin
        for origin in plan.module.origins
        if isinstance(origin.generated, TypeAliasDeclaration)
    )
    assert len(alias_origins) == 1
    assert alias_origins[0].origin == plan.source.aliases[1].span
    assert alias_origins[0].generated is plan.module.declarations[1]

    document = transform_source(source, path, maximum_arity=1).unwrap()

    authored_alias = f"type Selected[T] = {authored_value}"
    projected_alias = f"type Selected[T] = {projected_value}"
    assert document.generated_text == source.replace(authored_alias, projected_alias)
    replacement = next(
        mapping
        for mapping in document.mappings
        if mapping.origin is MappingKind.GENERATED
    )
    assert source[
        replacement.authored.start.offset : replacement.authored.end.offset
    ] == (authored_alias)
    assert (
        document.generated_text[
            replacement.generated.start.offset : replacement.generated.end.offset
        ]
        == projected_alias
    )


def test_overlay_preserves_compilation_failure_before_generating_overloads(
    monkeypatch: MonkeyPatch,
) -> None:
    source = dedent("""\
        from typeforge import Collect, Each

        def collect[T](*values: Each[T]) -> Collect[T]: ...
        """)
    path = Path("collect.py")
    error = AdaptationError("collect", "Each[T]", "cannot adapt this annotation")

    def reject_annotation(module: SourceModule) -> Failure[AdaptationError]:
        assert module.path == path
        assert module.functions[0].name == "collect"
        return Failure(error)

    monkeypatch.setattr(_compilation, "adapt_source_module", reject_annotation)

    result = transform_source(source, path, maximum_arity=1)

    assert result == Failure(
        OverlayError(OverlayErrorCode.ADAPTATION, path, error.message)
    )


def test_alias_generated_overloads_have_origins_for_functions_and_methods() -> None:
    source = dedent("""\
        from typeforge import Case, Default, Map

        type Encoded[T] = Map[T, Case[int, bytes], Default[str]]

        def encode[T](value: T) -> Encoded[T]: ...

        class Encoder:
            def encode[T](self, value: T) -> Encoded[T]: ...
        """)
    plan = compile_source(source, Path("encoding.py"), maximum_arity=1).unwrap()
    overload_origins = tuple(
        origin
        for origin in plan.module.origins
        if isinstance(origin.generated, OverloadDeclaration)
    )

    assert tuple(origin.origin for origin in overload_origins) == tuple(
        function.span for function in plan.source.functions
    )
    assert len(overload_origins) == 2
    assert overload_origins[0].generated is not overload_origins[1].generated


def test_equal_method_overloads_keep_their_authored_insertions_and_mappings() -> None:
    source = dedent("""\
        from typeforge import Collect, Each

        class First:
            @staticmethod
            def collect[T](*values: Each[T]) -> Collect[T]: ...

        class Second:
            @staticmethod
            def collect[T](*values: Each[T]) -> Collect[T]: ...

        while ready():
            serve()
        """)
    document = transform_source(source, Path("methods.py"), maximum_arity=0).unwrap()
    expected_block = dedent("""\
        if TYPE_CHECKING:  # typeforge: overlay
            @overload
            @staticmethod
            def collect() -> tuple[()]: ...
            @overload
            @staticmethod
            def collect[T](*values: T) -> tuple[T, ...]: ...
        # typeforge: overlay-end
        """)
    indented_block = "".join(f"    {line}\n" for line in expected_block.splitlines())
    assert document.generated_text == (
        "from typing import TYPE_CHECKING, overload  # typeforge: overlay-import\n"
        + source.replace("    @staticmethod\n", indented_block + "    @staticmethod\n")
    )
    overload_mappings = tuple(
        mapping
        for mapping in document.mappings
        if mapping.origin is MappingKind.GENERATED
        and document.generated_text[
            mapping.generated.start.offset : mapping.generated.end.offset
        ]
        == indented_block
    )
    assert len(overload_mappings) == 2
    for mapping, source_line in zip(overload_mappings, (4, 8), strict=True):
        assert mapping.authored.start.line == source_line
        assert (
            source[mapping.authored.start.offset : mapping.authored.end.offset]
            == "def collect[T](*values: Each[T]) -> Collect[T]: ..."
        )


def test_record_overloads_remain_excluded_from_overlay_insertion() -> None:
    source = dedent("""\
        from typing import TypedDict
        from typeforge import Field, Key, MapFields, Value

        class User(TypedDict):
            name: str

        type Copy[T] = MapFields[T, Field[Key, Value]]

        def copy[T](value: T) -> Copy[T]: ...
        """)
    document = transform_source(source, Path("records.py"), maximum_arity=1).unwrap()

    assert document.generated_text == source.replace(
        "type Copy[T] = MapFields[T, Field[Key, Value]]", "type Copy[T] = object"
    )


def test_specialization_failure_is_reported_before_overlay_edits() -> None:
    source = dedent("""\
        from typeforge import Each

        def invalid[T](value: Each[T]) -> T: ...
        """)
    path = Path("invalid.py")

    result = transform_source(source, path, maximum_arity=1)

    assert result == Failure(
        OverlayError(
            OverlayErrorCode.LOWERING,
            path,
            "Each must annotate a variadic positional parameter",
        )
    )


@mark.parametrize(
    "maximum_arity", (0, -1), ids=("already-transformed", "invalid-arity")
)
def test_overlay_sentinel_and_invalid_arity_short_circuit_compilation(
    monkeypatch: MonkeyPatch, maximum_arity: int
) -> None:
    source = "# typeforge: overlay\nthis is already transformed\n"
    path = Path("already_transformed.py")

    def unexpected_compilation(module: SourceModule) -> Failure[AdaptationError]:
        raise AssertionError(f"must not compile {module.path}")

    monkeypatch.setattr(_compilation, "adapt_source_module", unexpected_compilation)
    monkeypatch.setattr(ast, "parse", unexpected_compilation)
    monkeypatch.setattr(
        "typeforge.overlay.transform.compile_source", unexpected_compilation
    )

    result = transform_source(source, path, maximum_arity=maximum_arity)

    if maximum_arity < 0:
        assert result == Failure(
            OverlayError(
                OverlayErrorCode.INVALID_ARITY,
                path,
                "maximum arity must be non-negative",
            )
        )
    else:
        assert result.unwrap().generated_text == source


@mark.parametrize(
    "scope",
    (
        "class Outer:\n    class Inner:",
        "if ready():\n    class Collector:",
        "class _Outer:\n    class Inner:",
        'if __name__ == "__main__":\n    class Collector:',
    ),
    ids=("nested-class", "conditional-class", "private-class", "main-guard"),
)
def test_scoped_method_overloads_remain_inside_their_authored_scope(scope: str) -> None:
    source = (
        "from typeforge import Each, Collect\n"
        f"{scope}\n"
        "        def collect[T](self, *values: Each[T]) -> Collect[T]: ...\n"
    )

    document = transform_source(source, Path("scoped.py"), maximum_arity=0).unwrap()

    assert f"{scope}\n        if TYPE_CHECKING:" in document.generated_text
    assert "            def collect(self: Any, /) -> tuple[()]: ..." in (
        document.generated_text
    )
    overload_mapping = next(
        mapping
        for mapping in document.mappings
        if mapping.origin is MappingKind.GENERATED
        and document.generated_text[
            mapping.generated.start.offset : mapping.generated.end.offset
        ].startswith("        if TYPE_CHECKING:")
    )
    assert overload_mapping.authored.start.offset == source.index("def collect")


@mark.parametrize(
    ("scope", "expected"),
    (
        (
            "class _Outer:\n    class Inner:",
            "from typing import Any\n\nclass _Outer:\n    pass\n",
        ),
        (
            'if __name__ == "__main__":\n    class Collector:',
            "from typing import Any\n",
        ),
    ),
    ids=("private-class", "main-guard"),
)
@mark.parametrize(
    "parameters",
    ("*values: Each[T]", "value: Each[T]"),
    ids=("valid-variadic", "ignored-invalid-variadic"),
)
def test_scoped_overlay_overloads_do_not_leak_into_published_module(
    tmp_path: Path, scope: str, expected: str, parameters: str
) -> None:
    source = (
        "from typeforge import Each, Collect\n"
        f"{scope}\n"
        f"        def collect[T](self, {parameters}) -> Collect[T]: ...\n"
    )
    path = tmp_path / "scoped.py"
    path.write_text(source, encoding="utf-8")

    published = generate_module(path, maximum_arity=1).unwrap()

    assert published.content == expected


def test_scoped_method_does_not_replace_a_same_named_record_consumer() -> None:
    source = dedent("""\
        from typing import TypedDict
        from typeforge import Collect, Each, Field, Key, MapFields, Value

        class User(TypedDict):
            name: str

        type Copy[T] = MapFields[T, Field[Key, Value]]

        def copy[T](value: T) -> Copy[T]: ...

        class Outer:
            class Inner:
                def copy[T](self, *values: Each[T]) -> Collect[T]: ...
        """)

    document = transform_source(source, Path("records.py"), maximum_arity=0).unwrap()

    assert "            def copy(self: Any, /) -> tuple[()]: ..." in (
        document.generated_text
    )
    plan = compile_source(source, Path("records.py"), maximum_arity=0).unwrap()
    record_overload = next(
        item.generated
        for item in plan.module.origins
        if item.origin == plan.source.functions[0].span
        and isinstance(item.generated, OverloadDeclaration)
    )
    assert tuple(
        parameter.name for parameter in record_overload.signatures[0].parameters
    ) == ("value",)


@mark.parametrize(
    ("annotation", "message"),
    [
        ("Map[int]", "Map requires a subject and at least one branch"),
        ("Each[int, str]", "Each requires one type argument"),
    ],
)
@mark.parametrize(
    "declaration",
    ["class Payload:\n    value: {annotation}\n", "class Payload({annotation}): ...\n"],
    ids=["class-field", "class-base"],
)
def test_malformed_class_markers_report_the_shared_compiler_failure(
    annotation: str, message: str, declaration: str
) -> None:
    source = "from typeforge import Each, Map\n" + declaration.format(
        annotation=annotation
    )
    path = Path("malformed.py")

    result = transform_source(source, path, maximum_arity=1)

    assert result == Failure(OverlayError(OverlayErrorCode.ADAPTATION, path, message))
