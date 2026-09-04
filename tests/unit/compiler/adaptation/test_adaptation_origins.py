from pathlib import Path

import pytest
from returns.result import Success

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.source import (
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    SourceModule,
    SourcePosition,
    SourceSpan,
    TypeParameter,
    TypeParameterKind,
    parse_source,
)
from typeforge.compiler.source import (
    TypeAliasDeclaration as SourceTypeAlias,
)
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    ClassField,
    FunctionDeclaration,
    GeneratedElementOrigin,
    MapCase,
    MapType,
    TypeAliasDeclaration,
    TypeName,
    TypeVariable,
)


def test_adapt_source_module_attaches_origin_to_enriched_function() -> None:
    path = Path("callables.py")
    source = parse_source(
        "from typeforge import Collect, Each\n"
        "def identity[T](value: T) -> T: ...\n"
        "def collect[*Ts](*values: Each[Ts]) -> Collect[Ts]: ...\n",
        path,
    ).unwrap()

    result = adapt_source_module(source)

    assert isinstance(result, Success)
    adapted = result.unwrap()
    generated_function = next(
        declaration
        for declaration in adapted.declarations
        if isinstance(declaration, FunctionDeclaration)
        and declaration.name == "collect"
    )
    assert adapted.origins == (
        GeneratedElementOrigin(source.functions[1].span, generated_function),
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="adaptation does not yet retain target-neutral generated origins",
)
def test_adapt_source_module_retains_target_neutral_alias_with_origin() -> None:
    path = Path("aliases.py")
    span = SourceSpan(path, SourcePosition(1, 0), SourcePosition(1, 62))
    type_variable = NameTypeExpression("T", span, ("T",), None)
    integer = NameTypeExpression("int", span, ("int",), None)
    string = NameTypeExpression("str", span, ("str",), None)
    bytes_type = NameTypeExpression("bytes", span, ("bytes",), None)
    source_alias = SourceTypeAlias(
        name="Encoded",
        qualified_name=("Encoded",),
        type_parameters=(TypeParameter("T", TypeParameterKind.TYPE_VAR, "T"),),
        value=MarkerTypeExpression(
            "Map[T, Case[int, str], Default[bytes]]",
            span,
            MarkerKind.MAP,
            (
                type_variable,
                MarkerTypeExpression(
                    "Case[int, str]",
                    span,
                    MarkerKind.CASE,
                    (integer, string),
                ),
                MarkerTypeExpression(
                    "Default[bytes]",
                    span,
                    MarkerKind.DEFAULT,
                    (bytes_type,),
                ),
            ),
        ),
        span=span,
    )

    result = adapt_source_module(SourceModule(path, (), aliases=(source_alias,)))

    assert isinstance(result, Success)
    generated_alias = TypeAliasDeclaration(
        "Encoded",
        MapType(
            TypeVariable("T"),
            (MapCase(TypeName("int"), TypeName("str")),),
            TypeName("bytes"),
        ),
        ("T",),
    )
    adapted = result.unwrap()
    assert adapted.declarations == (generated_alias,)
    assert adapted.origins == (
        GeneratedElementOrigin(source_alias.span, generated_alias),
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="adaptation does not yet materialize records with authored origins",
)
def test_adapt_source_module_materializes_record_with_origin() -> None:
    path = Path("records.py")
    source = parse_source(
        "from typing import TypedDict\nclass Payload(TypedDict):\n    value: int\n",
        path,
    ).unwrap()

    result = adapt_source_module(source)

    assert isinstance(result, Success)
    generated_record = ClassDeclaration(
        name="Payload",
        bases=(TypeName("tf_typing.TypedDict"),),
        fields=(ClassField("value", TypeName("int")),),
        methods=(),
    )
    adapted = result.unwrap()
    assert adapted.declarations == (generated_record,)
    assert adapted.origins == (
        GeneratedElementOrigin(source.typed_dicts[0].span, generated_record),
    )
