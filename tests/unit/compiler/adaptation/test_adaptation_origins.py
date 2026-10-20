from pathlib import Path

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
    OverloadDeclaration,
    TypeAliasDeclaration,
    TypeName,
    TypeVariable,
    walk_module,
)


def test_adapt_source_module_attaches_origin_to_enriched_function() -> None:
    path = Path("callables.py")
    source = (
        parse_source(
            "from typeforge import Collect, Each\n"
            "def identity[T](value: T) -> T: ...\n"
            "def collect[*Ts](*values: Each[Ts]) -> Collect[Ts]: ...\n",
            path,
        )
        .unwrap()
        .source
    )

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
            "Map[T, int : str, ... : bytes]",
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
        GeneratedElementOrigin(source_alias.span, adapted.reusable_elements[0]),
    )
    assert adapted.origins[0].generated is adapted.declarations[0]


def test_adapt_source_module_does_not_attach_origin_to_ordinary_alias() -> None:
    source = parse_source("type Label = str\n", Path("aliases.py")).unwrap().source

    adapted = adapt_source_module(source).unwrap()

    assert adapted.origins == ()


def test_adapt_source_module_materializes_record_with_origin() -> None:
    path = Path("records.py")
    source = (
        parse_source(
            "from typing import TypedDict\nclass Payload(TypedDict):\n    value: int\n",
            path,
        )
        .unwrap()
        .source
    )

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


def test_record_replacements_retain_current_authored_origins() -> None:
    source = (
        parse_source(
            """\
from typing import TypedDict
from typeforge import Collect, Each, Field, Map, Fields, Record
class Payload(TypedDict):
    value: int
type Copy[T] = Record((Field[field.name, field.type] for field in Fields[T]))
type Encoded[T] = Map[T, int : Copy[Payload]]
def copy[T](value: T) -> Copy[T]: ...
def collect[*Ts](*values: Each[Ts]) -> Collect[Copy[Payload]]: ...
""",
            Path("records.py"),
        )
        .unwrap()
        .source
    )

    adapted = adapt_source_module(source).unwrap()

    payload, copied, copy_alias, encoded, copy, collect = adapted.declarations
    assert isinstance(copied, ClassDeclaration)
    assert copied.name == "Copy_Payload"
    assert isinstance(encoded, TypeAliasDeclaration)
    assert isinstance(encoded.value, MapType)
    assert encoded.value.cases[0].output_type == TypeName("Copy_Payload")
    assert isinstance(copy, OverloadDeclaration)
    assert copy.signatures[0].return_type == TypeName("Copy_Payload")
    assert isinstance(collect, FunctionDeclaration)
    assert adapted.origins == (
        GeneratedElementOrigin(source.typed_dicts[0].span, payload),
        GeneratedElementOrigin(source.typed_dicts[0].span, copied),
        GeneratedElementOrigin(source.aliases[0].span, copied),
        GeneratedElementOrigin(source.aliases[0].span, copy_alias),
        GeneratedElementOrigin(source.aliases[1].span, encoded),
        GeneratedElementOrigin(source.aliases[1].span, adapted.reusable_elements[0]),
        GeneratedElementOrigin(source.functions[0].span, copy),
        GeneratedElementOrigin(source.functions[1].span, collect),
    )
    assert all(
        any(item.generated is element for element in walk_module(adapted))
        for item in adapted.origins
    )
    assert adapt_source_module(source).unwrap() == adapted
