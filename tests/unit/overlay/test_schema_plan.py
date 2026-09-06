from pathlib import Path
from textwrap import dedent

from pytest import mark
from returns.result import Failure

from typeforge.compiler.pipeline import compile_source, generate_module
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    CollectType,
    TypeName,
    walk_declaration,
)
from typeforge.overlay import OverlayError, OverlayErrorCode, transform_source


def test_schema_roots_cover_records_and_scoped_methods() -> None:
    source = dedent("""\
        from typing import TypedDict
        from typeforge import Field, Key, MapFields, Value
        from typeforge.pydantic import Schema
        class Payload(TypedDict):
            value: Schema[int]
        type Copy[T] = MapFields[T, Field[Key, Value]]
        class Outer:
            class Inner:
                def parse(self, value: Schema[Copy[Payload]]) -> Schema[bytes]: ...
        """)
    path = Path("schemas.py")

    plan = compile_source(source, path, maximum_arity=1).unwrap()

    assert plan.module.expressions == (
        TypeName("Copy_Payload"),
        TypeName("bytes"),
        TypeName("int"),
    )
    schema_origins = tuple(
        origin
        for origin in plan.module.origins
        if any(origin.generated is root for root in plan.module.expressions)
    )
    assert tuple(origin.origin.start.line for origin in schema_origins) == (5, 9, 9)
    copied_record = next(
        declaration
        for declaration in plan.module.declarations
        if isinstance(declaration, ClassDeclaration)
        and declaration.name == "Copy_Payload"
    )
    assert copied_record.fields[0].annotation == TypeName("Schema[int]")

    document = transform_source(source, path, maximum_arity=1).unwrap()

    assert "value: int" in document.generated_text
    assert "value: Copy_Payload) -> bytes" in document.generated_text
    assert document.generated_text.count("class Copy_Payload(") == 1
    assert "    value: Schema[int]" in document.generated_text


def test_schema_roots_preserve_unspecialized_emission_failures() -> None:
    source = dedent("""\
        from typeforge import Collect, Each
        from typeforge.pydantic import Schema
        def gather[*Ts](*values: Each[Ts]) -> Schema[Collect[Ts]]: ...
        """)
    path = Path("schemas.py")

    plan = compile_source(source, path, maximum_arity=1).unwrap()

    assert plan.module.expressions == (CollectType(TypeName("Ts")),)
    result = transform_source(source, path, maximum_arity=1)
    assert isinstance(result, Failure)
    assert result.failure().code is OverlayErrorCode.EMISSION


def test_shared_alias_outputs_do_not_create_overlapping_schema_edits() -> None:
    source = dedent("""\
        from typeforge import Case, Default, Map
        from typeforge.pydantic import Schema
        type Item[T] = Map[T, Case[int, str], Default[bytes]]
        class Payload:
            a: Schema[Item[int]]
            b: Schema[tuple[Schema[Item[int]], int]]
        """)

    plan = compile_source(source, Path("schemas.py"), maximum_arity=1).unwrap()
    _alias, first_schema, outer_schema = plan.module.expressions
    schema_roots = (first_schema, outer_schema)
    declaration_nodes = tuple(
        node
        for declaration in plan.module.declarations
        for node in walk_declaration(declaration)
    )
    assert all(root is not node for root in schema_roots for node in declaration_nodes)
    assert tuple(
        (origin.origin.start.line, origin.generated)
        for origin in plan.module.origins
        if any(origin.generated is root for root in schema_roots)
    ) == ((5, first_schema), (6, outer_schema))

    document = transform_source(source, Path("schemas.py")).unwrap()

    assert document.generated_text == dedent("""\
        from typeforge import Case, Default, Map
        from typeforge.pydantic import Schema
        type Item[T] = str | bytes
        class Payload:
            a: str
            b: tuple[str, int]
        """)


@mark.parametrize(
    "annotation",
    ("Schema[int]", "Schema[int, str]"),
    ids=("valid-schema", "malformed-schema"),
)
def test_published_record_annotations_remain_opaque(
    tmp_path: Path, annotation: str
) -> None:
    source = dedent(f"""\
        from typing import TypedDict
        from typeforge.pydantic import Schema
        class Payload(TypedDict):
            value: {annotation}
        """)
    path = tmp_path / "records.py"
    path.write_text(source, encoding="utf-8")

    published = generate_module(path, maximum_arity=1).unwrap()

    assert published.content == dedent(f"""\
        import typing as tf_typing
        from typing import TypedDict

        class Payload(tf_typing.TypedDict):
            value: {annotation}
        """)
    overlay = transform_source(source, path, maximum_arity=1)
    if annotation == "Schema[int]":
        assert overlay.unwrap().generated_text == source.replace(annotation, "int")
    else:
        assert overlay == Failure(
            OverlayError(
                OverlayErrorCode.ADAPTATION, path, "Schema requires one type argument"
            )
        )
