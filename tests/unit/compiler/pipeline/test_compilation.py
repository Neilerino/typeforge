from pathlib import Path
from textwrap import dedent

import pytest
from returns.result import Failure, Success

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.pipeline import (
    RecordMaterializationError,
    compile_source,
    generate_module,
)
from typeforge.compiler.source import SourcePosition, SourceSpan, parse_source
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    ClassField,
    FixedTuple,
    FunctionDeclaration,
    GeneratedElement,
    GeneratedElementOrigin,
    OverloadDeclaration,
    Parameter,
    ParameterKind,
    StubModule,
    TypeAliasDeclaration,
    TypeApplication,
    TypeName,
    UnionExpression,
    UnpackedType,
    walk_declaration,
    walk_module,
)

SCHEMA_PATH = Path("schemas.py")


def test_compile_source_associates_enriched_function_with_generated_overload() -> None:
    path = Path("callables.py")
    source = dedent("""\
        from typeforge import Collect, Each
        def identity[T](value: T) -> T: ...
        def collect[*Ts](*values: Each[Ts]) -> Collect[Ts]: ...
        """)

    result = compile_source(source, path, maximum_arity=1)

    assert isinstance(result, Success)
    plan = result.unwrap()
    identity, collect = plan.source.functions
    overload = next(
        declaration
        for declaration in plan.module.declarations
        if isinstance(declaration, OverloadDeclaration)
        and declaration.fallback.name == "collect"
    )
    assert plan.module.origins == (GeneratedElementOrigin(collect.span, overload),)
    assert all(item.origin != identity.span for item in plan.module.origins)


def test_compile_source_keeps_record_origins_in_specialized_snapshot() -> None:
    plan = compile_source(
        dedent("""\
            from typing import TypedDict
            class Payload(TypedDict):
                value: int
            """),
        Path("records.py"),
        maximum_arity=1,
    ).unwrap()

    assert len(plan.module.origins) == 1
    assert plan.module.origins[0].origin == plan.source.typed_dicts[0].span
    assert plan.module.origins[0].generated is plan.module.declarations[0]


def test_shared_derived_records_keep_only_their_alias_and_input_origins() -> None:
    source = dedent("""\
from typing import TypedDict
from typeforge import Field, Fields, Record
class Payload(TypedDict):
    value: int
class Message(TypedDict):
    text: bytes
type Copy[T] = Record((Field[field.name, field.type] for field in Fields[T]))
type Stringify[T] = Record((Field[field.name, str] for field in Fields[T]))
def copy[T](value: T) -> Copy[T]: ...
def copy_again[T](value: T) -> Copy[T]: ...
def ordinary(value: Payload) -> Payload: ...
""")

    plan = compile_source(source, Path("records.py"), maximum_arity=1).unwrap()

    (
        payload,
        message,
        copied_payload,
        copied_message,
        stringified_payload,
        stringified_message,
        copy_alias,
        stringify_alias,
        copy,
        copy_again,
        ordinary,
    ) = plan.module.declarations
    assert isinstance(copied_payload, ClassDeclaration)
    assert copied_payload.name == "Copy_Payload"
    assert isinstance(copied_message, ClassDeclaration)
    assert copied_message.name == "Copy_Message"
    assert isinstance(copy, OverloadDeclaration)
    assert isinstance(copy_again, OverloadDeclaration)
    for consumer in (copy, copy_again):
        assert tuple(signature.return_type for signature in consumer.signatures) == (
            TypeName(copied_payload.name),
            TypeName(copied_message.name),
        )

    authored_payload, authored_message = plan.source.typed_dicts
    authored_copy, authored_stringify = plan.source.aliases
    first_consumer, second_consumer, _ = plan.source.functions
    _assert_origins(
        plan.module.origins,
        (
            (authored_payload.span, payload),
            (authored_payload.span, copied_payload),
            (authored_payload.span, stringified_payload),
            (authored_message.span, message),
            (authored_message.span, copied_message),
            (authored_message.span, stringified_message),
            (authored_copy.span, copied_payload),
            (authored_copy.span, copied_message),
            (authored_copy.span, copy_alias),
            (authored_stringify.span, stringified_payload),
            (authored_stringify.span, stringified_message),
            (authored_stringify.span, stringify_alias),
            (first_consumer.span, copy),
            (second_consumer.span, copy_again),
        ),
    )
    assert all(origin.generated is not ordinary for origin in plan.module.origins)
    _assert_origins_are_current(plan.module)
    assert compile_source(source, Path("records.py"), maximum_arity=1).unwrap() == plan


def test_derived_record_origins_follow_source_order_when_alias_precedes_input() -> None:
    source = dedent("""\
from typing import TypedDict
from typeforge import Field, Fields, Record
type Copy[T] = Record((Field[field.name, field.type] for field in Fields[T]))
class Payload(TypedDict):
    value: int
""")

    plan = compile_source(source, Path("records.py"), maximum_arity=1).unwrap()

    payload, copied_payload, copy_alias = plan.module.declarations
    authored_copy = plan.source.aliases[0]
    authored_payload = plan.source.typed_dicts[0]
    _assert_origins(
        plan.module.origins,
        (
            (authored_copy.span, copied_payload),
            (authored_copy.span, copy_alias),
            (authored_payload.span, payload),
            (authored_payload.span, copied_payload),
        ),
    )
    _assert_origins_are_current(plan.module)


@pytest.mark.parametrize(
    "record_declaration",
    [
        pytest.param("", id="without-record-materialization"),
        pytest.param(
            dedent("""\
                from typing import TypedDict
                class Payload(TypedDict):
                    value: int
                """),
            id="with-record-materialization",
        ),
    ],
)
def test_equal_methods_in_different_classes_keep_their_own_origins(
    record_declaration: str,
) -> None:
    source = record_declaration + dedent("""\
        from typeforge import Collect, Each
        class First:
            def identity[T](self: object, value: T) -> T: ...
            def collect[*Ts](self: object, *values: Each[Ts]) -> Collect[Ts]: ...
        class Second:
            def identity[T](self: object, value: T) -> T: ...
            def collect[*Ts](self: object, *values: Each[Ts]) -> Collect[Ts]: ...
        """)

    plan = compile_source(source, Path("methods.py"), maximum_arity=1).unwrap()

    first_class, second_class = (
        declaration
        for declaration in plan.module.declarations
        if isinstance(declaration, ClassDeclaration)
        and declaration.name in {"First", "Second"}
    )
    first_identity, first_overload = first_class.methods
    second_identity, second_overload = second_class.methods
    assert isinstance(first_identity, FunctionDeclaration)
    assert isinstance(second_identity, FunctionDeclaration)
    assert isinstance(first_overload, OverloadDeclaration)
    assert isinstance(second_overload, OverloadDeclaration)
    assert first_overload == second_overload
    assert first_overload is not second_overload

    record_spans = {record.span for record in plan.source.typed_dicts}
    non_record_origins = tuple(
        origin for origin in plan.module.origins if origin.origin not in record_spans
    )
    first_authored, second_authored = plan.source.classes
    _assert_origins(
        non_record_origins,
        (
            (first_authored.methods[1].span, first_overload),
            (second_authored.methods[1].span, second_overload),
        ),
    )


def test_compilation_preserves_metadata_when_rewriting_classes_and_methods() -> None:
    source = dedent("""\
from typing import TypedDict
from typeforge import Collect, Each, Field, Fields, Record
class Payload(TypedDict):
    value: int
type Copy[T] = Record((Field[field.name, field.type] for field in Fields[T]))
@decorate
class Consumer[U](Base, metaclass=Meta):
    cached: Copy[Payload] = ...
    @custom
    async def collect[*Ts](
        self: object, *values: Each[Ts], label: str = 'label'
    ) -> Collect[Ts]: ...
    @custom
    async def read(
        self: object, *, value: Copy[Payload] = ...
    ) -> Copy[Payload]: ...
""")

    plan = compile_source(source, Path("metadata.py"), maximum_arity=1).unwrap()

    consumer = next(
        item
        for item in plan.module.declarations
        if isinstance(item, ClassDeclaration) and item.name == "Consumer"
    )
    assert consumer.bases == (TypeName("Base"),)
    assert consumer.type_parameters == ("U",)
    assert consumer.keywords == ("metaclass=Meta",)
    assert consumer.decorators == ("decorate",)
    assert consumer.fields == (ClassField("cached", TypeName("Copy_Payload"), "..."),)
    collect, read = consumer.methods
    assert isinstance(collect, OverloadDeclaration)
    assert isinstance(read, FunctionDeclaration)
    assert plan.module.origins[-1].origin == plan.source.classes[0].methods[0].span
    assert plan.module.origins[-1].generated is collect
    for signature in (*collect.signatures, collect.fallback, read):
        assert signature.is_async
        assert signature.decorators == ("custom",)

    for signature in (*collect.signatures, collect.fallback):
        assert signature.parameters[-1] == Parameter(
            "label", TypeName("str"), ParameterKind.KEYWORD_ONLY, "..."
        )

    assert read.return_type == TypeName("Copy_Payload")
    assert read.parameters[-1] == Parameter(
        "value", TypeName("Copy_Payload"), ParameterKind.KEYWORD_ONLY, "..."
    )


def test_record_failure_propagates_before_specialization(tmp_path: Path) -> None:
    source = dedent("""\
from typing import TypedDict
from typeforge import Field, Fields, Record
class Payload(TypedDict):
    value: int
type Copy = Record((Field[field.name, field.type] for field in Fields[Payload]))
""")
    path = tmp_path / "records.py"
    path.write_text(source, encoding="utf-8")
    expected = RecordMaterializationError(
        declaration="Copy",
        expression=(
            "Record((Field[field.name, field.type] for field in Fields[Payload]))"
        ),
        message="record aliases require exactly one type parameter",
    )

    adapted = adapt_source_module(parse_source(source, path).unwrap().source)
    compiled = compile_source(source, path, maximum_arity=-1)
    generated = generate_module(path, maximum_arity=-1)

    assert adapted == Failure(expected)
    assert compiled == Failure(expected)
    assert generated == Failure(expected)


def test_nested_schema_origin_tracks_the_inner_type_and_its_span() -> None:
    source = dedent("""\
        from typeforge.pydantic import Schema
        def parse(value: list[Schema[int]]) -> str: ...
        """)

    plan = compile_source(source, SCHEMA_PATH, maximum_arity=1).unwrap()

    function = plan.module.declarations[0]
    assert isinstance(function, FunctionDeclaration)
    list_annotation = function.parameters[0].annotation
    assert isinstance(list_annotation, TypeApplication)
    generated_integer = list_annotation.arguments[0]
    assert generated_integer == TypeName("int")
    _assert_origins(
        plan.module.origins,
        (
            (_span_of(source, "Schema[int]"), generated_integer),
            (_span_of(source, "Schema[int]"), plan.module.reusable_elements[0]),
        ),
    )


def test_repeated_schemas_keep_distinct_origins_and_plain_types_get_none() -> None:
    source = dedent("""\
        from typeforge.pydantic import Schema
        def parse(
            value: tuple[Schema[int], Schema[int], int],
        ) -> Schema[list[Schema[int]]]: ...
        """)

    plan = compile_source(source, SCHEMA_PATH, maximum_arity=1).unwrap()

    first_replacement, second_replacement, return_replacement = (
        plan.module.reusable_elements
    )
    function = plan.module.declarations[0]
    assert isinstance(function, FunctionDeclaration)
    parameter_tuple = function.parameters[0].annotation
    returned_list = function.return_type
    assert isinstance(parameter_tuple, TypeApplication)
    assert isinstance(returned_list, TypeApplication)
    first_integer, second_integer, plain_integer = parameter_tuple.arguments
    assert first_integer == second_integer
    assert first_integer is not second_integer
    assert all(origin.generated is not plain_integer for origin in plan.module.origins)
    _assert_origins(
        plan.module.origins,
        (
            (_span_of(source, "Schema[int]", occurrence=1), first_integer),
            (_span_of(source, "Schema[int]", occurrence=1), first_replacement),
            (_span_of(source, "Schema[int]", occurrence=2), second_integer),
            (_span_of(source, "Schema[int]", occurrence=2), second_replacement),
            (_span_of(source, "Schema[list[Schema[int]]]"), returned_list),
            (_span_of(source, "Schema[list[Schema[int]]]"), return_replacement),
            (_span_of(source, "Schema[int]", occurrence=3), returned_list.arguments[0]),
        ),
    )


def test_collapsing_equal_schema_results_retains_all_three_authored_causes() -> None:
    source = dedent("""\
        from typeforge.pydantic import Schema
        type Selected = Schema[Schema[int] | Schema[int]]
        """)

    plan = compile_source(source, SCHEMA_PATH, maximum_arity=1).unwrap()

    alias = plan.module.declarations[0]
    assert isinstance(alias, TypeAliasDeclaration)
    assert alias.value == TypeName("int")
    _assert_origins(
        plan.module.origins,
        (
            (plan.source.aliases[0].span, alias),
            (_span_of(source, "Schema[Schema[int] | Schema[int]]"), alias.value),
            (_span_of(source, "Schema[int]", occurrence=1), alias.value),
            (_span_of(source, "Schema[int]", occurrence=2), alias.value),
        ),
    )


@pytest.mark.parametrize(
    "source, expected_field_type",
    [
        pytest.param(
            dedent("""\
                from typeforge.pydantic import Schema
                class Consumer:
                    field: Schema[list[int]]
                    def parse(
                        self: object, value: Schema[list[int]]
                    ) -> Schema[int]: ...
                """),
            "int",
            id="ordinary-class-rewrite",
        ),
        pytest.param(
            dedent("""\
from typeforge.pydantic import Schema
from typing import TypedDict
from typeforge import Field, Fields, Record
class Payload(TypedDict):
    value: int
type Copy[T] = Record((Field[field.name, field.type] for field in Fields[T]))
class Consumer:
    field: Schema[list[Copy[Payload]]]
    def parse(
        self: object, value: Schema[list[int]]
    ) -> Schema[int]: ...
"""),
            "Copy_Payload",
            id="record-alias-rewrite",
        ),
    ],
)
def test_class_rewrites_preserve_field_parameter_and_return_schema_origins(
    source: str,
    expected_field_type: str,
) -> None:
    plan = compile_source(source, SCHEMA_PATH, maximum_arity=1).unwrap()

    parameter_replacement, return_replacement, field_replacement = (
        plan.module.reusable_elements
    )
    consumer = next(
        declaration
        for declaration in plan.module.declarations
        if isinstance(declaration, ClassDeclaration) and declaration.name == "Consumer"
    )
    field_annotation = consumer.fields[0].annotation
    assert field_annotation == TypeApplication(
        TypeName("list"), (TypeName(expected_field_type),)
    )
    method = consumer.methods[0]
    assert isinstance(method, FunctionDeclaration)
    authored_class = plan.source.classes[0]
    authored_field_schema = authored_class.fields[0].annotation
    authored_parameter_schema = authored_class.methods[0].parameters[1].annotation
    authored_return_schema = authored_class.methods[0].returns
    assert authored_parameter_schema is not None
    assert authored_return_schema is not None
    class_origins = tuple(
        origin
        for origin in plan.module.origins
        if origin.origin.start >= authored_class.span.start
    )
    _assert_origins(
        class_origins,
        (
            (authored_field_schema.span, field_annotation),
            (authored_field_schema.span, field_replacement),
            (authored_parameter_schema.span, method.parameters[1].annotation),
            (authored_parameter_schema.span, parameter_replacement),
            (authored_return_schema.span, method.return_type),
            (authored_return_schema.span, return_replacement),
        ),
    )


def test_flattening_an_inner_schema_union_attaches_its_origin_to_each_member() -> None:
    source = dedent("""\
        from typeforge.pydantic import Schema
        type Selected = Schema[Schema[int | str] | bytes]
        """)

    plan = compile_source(source, SCHEMA_PATH, maximum_arity=1).unwrap()

    alias = plan.module.declarations[0]
    assert isinstance(alias, TypeAliasDeclaration)
    flattened_union = alias.value
    assert isinstance(flattened_union, UnionExpression)
    integer, string, _bytes = flattened_union.members
    inner_schema = _span_of(source, "Schema[int | str]")
    _assert_origins(
        plan.module.origins,
        (
            (plan.source.aliases[0].span, alias),
            (_span_of(source, "Schema[Schema[int | str] | bytes]"), flattened_union),
            (inner_schema, integer),
            (inner_schema, string),
        ),
    )


def test_deduplicating_equal_containers_preserves_both_inner_schema_origins() -> None:
    source = dedent("""\
        from typeforge.pydantic import Schema
        type Selected = Schema[list[Schema[int]] | list[Schema[int]]]
        """)

    plan = compile_source(source, SCHEMA_PATH, maximum_arity=1).unwrap()

    alias = plan.module.declarations[0]
    assert isinstance(alias, TypeAliasDeclaration)
    retained_list = alias.value
    assert isinstance(retained_list, TypeApplication)
    retained_integer = retained_list.arguments[0]
    _assert_origins(
        plan.module.origins,
        (
            (plan.source.aliases[0].span, alias),
            (
                _span_of(source, "Schema[list[Schema[int]] | list[Schema[int]]]"),
                retained_list,
            ),
            (_span_of(source, "Schema[int]", occurrence=1), retained_integer),
            (_span_of(source, "Schema[int]", occurrence=2), retained_integer),
        ),
    )


def test_schema_around_each_and_collect_tracks_whole_specialized_types() -> None:
    source = dedent("""\
        from typeforge import Collect, Each
        from typeforge.pydantic import Schema
        def gather[*Ts](*values: Schema[Each[Ts]]) -> Schema[Collect[Ts]]: ...
        """)

    plan = compile_source(source, SCHEMA_PATH, maximum_arity=2).unwrap()

    reusable_input, reusable_output = plan.module.reusable_elements
    overload = plan.module.declarations[0]
    assert isinstance(overload, OverloadDeclaration)
    zero_arguments, one_argument, two_arguments = overload.signatures
    fallback = overload.fallback
    for signature in overload.signatures:
        assert isinstance(signature.return_type, FixedTuple)

    input_schema = _span_of(source, "Schema[Each[Ts]]")
    output_schema = _span_of(source, "Schema[Collect[Ts]]")
    _assert_origins(
        plan.module.origins,
        (
            (plan.source.functions[0].span, overload),
            (input_schema, one_argument.parameters[0].annotation),
            (input_schema, two_arguments.parameters[0].annotation),
            (input_schema, two_arguments.parameters[1].annotation),
            (input_schema, fallback.parameters[0].annotation),
            (input_schema, reusable_input),
            (output_schema, zero_arguments.return_type),
            (output_schema, one_argument.return_type),
            (output_schema, two_arguments.return_type),
            (output_schema, fallback.return_type),
            (output_schema, reusable_output),
        ),
    )
    _assert_origins_are_current(plan.module)


def test_schema_inside_each_and_collect_tracks_individual_type_arguments() -> None:
    source = dedent("""\
        from typeforge import Collect, Each
        from typeforge.pydantic import Schema
        def gather[*Ts](*values: Each[Schema[Ts]]) -> Collect[Schema[Ts]]: ...
        """)

    plan = compile_source(source, SCHEMA_PATH, maximum_arity=2).unwrap()

    reusable_input, reusable_output = plan.module.reusable_elements
    overload = plan.module.declarations[0]
    assert isinstance(overload, OverloadDeclaration)
    zero_arguments, one_argument, two_arguments = overload.signatures
    assert zero_arguments.return_type == FixedTuple(())
    one_result = one_argument.return_type
    two_results = two_arguments.return_type
    fallback_result = overload.fallback.return_type
    fallback_input = overload.fallback.parameters[0].annotation
    assert isinstance(one_result, FixedTuple)
    assert isinstance(two_results, FixedTuple)
    assert isinstance(fallback_result, FixedTuple)
    assert isinstance(fallback_input, UnpackedType)
    fallback_output = fallback_result.items[0]
    assert isinstance(fallback_output, UnpackedType)

    input_schema = _span_of(source, "Schema[Ts]", occurrence=1)
    output_schema = _span_of(source, "Schema[Ts]", occurrence=2)
    _assert_origins(
        plan.module.origins,
        (
            (plan.source.functions[0].span, overload),
            (input_schema, one_argument.parameters[0].annotation),
            (input_schema, two_arguments.parameters[0].annotation),
            (input_schema, two_arguments.parameters[1].annotation),
            (input_schema, fallback_input.item),
            (input_schema, reusable_input),
            (output_schema, one_result.items[0]),
            (output_schema, two_results.items[0]),
            (output_schema, two_results.items[1]),
            (output_schema, fallback_output.item),
            (output_schema, reusable_output),
        ),
    )
    _assert_origins_are_current(plan.module)


def test_composite_schema_results_are_ordered_by_source_then_overload_arity() -> None:
    source = dedent("""\
        from typeforge import Collect, Each
        from typeforge.pydantic import Schema
        def gather[*Ts](
            *values: Each[Schema[list[Ts]]],
        ) -> Schema[tuple[*Collect[Ts]]]: ...
        """)

    plan = compile_source(source, SCHEMA_PATH, maximum_arity=2).unwrap()

    reusable_input, reusable_output = plan.module.reusable_elements
    overload = plan.module.declarations[0]
    assert isinstance(overload, OverloadDeclaration)
    zero_arguments, one_argument, two_arguments = overload.signatures
    fallback = overload.fallback
    input_schema = _span_of(source, "Schema[list[Ts]]")
    output_schema = _span_of(source, "Schema[tuple[*Collect[Ts]]]")
    _assert_origins(
        plan.module.origins,
        (
            (plan.source.functions[0].span, overload),
            (input_schema, one_argument.parameters[0].annotation),
            (input_schema, two_arguments.parameters[0].annotation),
            (input_schema, two_arguments.parameters[1].annotation),
            (input_schema, fallback.parameters[0].annotation),
            (input_schema, reusable_input),
            (output_schema, zero_arguments.return_type),
            (output_schema, one_argument.return_type),
            (output_schema, two_arguments.return_type),
            (output_schema, fallback.return_type),
            (output_schema, reusable_output),
        ),
    )
    assert compile_source(source, SCHEMA_PATH, maximum_arity=2).unwrap() == plan


def test_relationship_alias_copies_keep_the_original_schema_span() -> None:
    source = dedent("""        from typeforge import Map
        from typeforge.pydantic import Schema
        type Selected[T] = Map[T, int : Schema[list[T]], ... : bytes]
        def first[T](value: T) -> Selected[T]: ...
        def second[T](value: T) -> Selected[T]: ...
        """)

    plan = compile_source(source, SCHEMA_PATH, maximum_arity=1).unwrap()

    schema_span = _span_of(source, "Schema[list[T]]")
    schema_results = tuple(
        origin.generated
        for origin in plan.module.origins
        if origin.origin == schema_span
    )
    assert schema_results
    _alias, first_overload, second_overload = plan.module.declarations
    for overload in (first_overload, second_overload):
        assert isinstance(overload, OverloadDeclaration)
        specialized_result = overload.signatures[0].return_type
        assert any(result is specialized_result for result in schema_results)
        fallback_elements = tuple(walk_declaration(overload.fallback))
        assert any(
            result is element
            for result in schema_results
            for element in fallback_elements
        )

    _assert_origins_are_current(plan.module)


def test_unpacked_collect_keeps_its_schema_origin_in_the_fallback() -> None:
    source = dedent("""\
        from typeforge import Collect, Each
        from typeforge.pydantic import Schema
        def gather[*Ts](*values: Each[Ts]) -> tuple[int, *Schema[Collect[Ts]]]: ...
        """)

    plan = compile_source(source, SCHEMA_PATH, maximum_arity=2).unwrap()

    overload = plan.module.declarations[0]
    assert isinstance(overload, OverloadDeclaration)
    fallback_tuple = overload.fallback.return_type
    assert isinstance(fallback_tuple, TypeApplication)
    unpacked_tail = fallback_tuple.arguments[1]
    assert isinstance(unpacked_tail, UnpackedType)
    schema_span = _span_of(source, "Schema[Collect[Ts]]")
    assert any(
        origin.origin == schema_span and origin.generated is unpacked_tail.item
        for origin in plan.module.origins
    )


def _span_of(source: str, expression: str, *, occurrence: int = 1) -> SourceSpan:
    """Locate the expected authored span independently of the compiler's parser."""
    start = -1
    for _ in range(occurrence):
        start = source.index(expression, start + 1)

    def position(offset: int) -> SourcePosition:
        before = source[:offset]
        return SourcePosition(
            line=before.count("\n") + 1,
            column=len(before.rsplit("\n", 1)[-1]),
        )

    return SourceSpan(SCHEMA_PATH, position(start), position(start + len(expression)))


def _assert_origins(
    actual: tuple[GeneratedElementOrigin[SourceSpan], ...],
    expected: tuple[tuple[SourceSpan, GeneratedElement], ...],
) -> None:
    """Check every association in order; equal-but-detached IR must not pass."""
    assert len(actual) == len(expected)
    for origin, (authored_span, generated_element) in zip(
        actual, expected, strict=True
    ):
        assert origin.origin == authored_span
        assert origin.generated is generated_element


def _assert_origins_are_current(module: StubModule) -> None:
    elements = tuple(walk_module(module))
    for origin in module.origins:
        assert any(origin.generated is element for element in elements)
