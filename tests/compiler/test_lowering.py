from typeforge._result import Err, Ok
from typeforge.compiler.emitter import emit_stub_module
from typeforge.compiler.lowering import (
    AllPredicate,
    AnyPredicate,
    ArityFrontier,
    AssignablePredicate,
    CollectType,
    EachType,
    EqualPredicate,
    FunctionDeclaration,
    IfType,
    ImportFrom,
    LiteralType,
    LoweringErrorCode,
    MapCase,
    MapType,
    NotPredicate,
    Parameter,
    ParameterKind,
    StubModule,
    TypeApplication,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    lower_variadic_module,
)


def parser_of(item: TypeVariable | CollectType) -> TypeApplication:
    return TypeApplication(TypeName("Parser"), (item,))


def variadic_module() -> StubModule:
    captured = TypeVariable("T")
    return StubModule(
        "example",
        (
            FunctionDeclaration(
                "combine",
                (
                    Parameter(
                        "parsers",
                        EachType(parser_of(captured)),
                        ParameterKind.VAR_POSITIONAL,
                    ),
                ),
                parser_of(CollectType(captured)),
                ("T",),
            ),
        ),
        (ImportFrom("example.parser", ("Parser",)),),
    )


def test_lowers_each_collect_to_deterministic_portable_overloads() -> None:
    lowered = lower_variadic_module(variadic_module(), ArityFrontier(0, 2))

    assert isinstance(lowered, Ok)
    emitted = emit_stub_module(lowered.value)
    assert emitted == Ok(
        "from example.parser import Parser\n"
        "from typing import overload\n\n"
        "@overload\n"
        "def combine() -> Parser[tuple[()]]: ...\n"
        "@overload\n"
        "def combine[T1](parsers_1: Parser[T1], /) -> Parser[tuple[T1]]: ...\n"
        "@overload\n"
        "def combine[T1, T2](parsers_1: Parser[T1], "
        "parsers_2: Parser[T2], /) -> Parser[tuple[T1, T2]]: ...\n"
        "@overload\n"
        "def combine[T](*parsers: Parser[T]) -> Parser[tuple[T, ...]]: ...\n"
    )


def test_flattens_unpacked_collect_inside_tuple_union() -> None:
    entity = TypeVariable("E")
    captured = TypeVariable("Ts")
    module = StubModule(
        "ecs",
        (
            FunctionDeclaration(
                "query",
                (
                    Parameter(
                        "components",
                        EachType(TypeApplication(TypeName("type"), (captured,))),
                        ParameterKind.VAR_POSITIONAL,
                    ),
                ),
                UnionExpression(
                    (
                        TypeApplication(
                            TypeName("tuple"),
                            (entity, UnpackedType(CollectType(captured))),
                        ),
                        TypeName("None"),
                    )
                ),
                ("E", "*Ts"),
            ),
        ),
    )

    lowered = lower_variadic_module(module, ArityFrontier(2, 2))

    assert isinstance(lowered, Ok)
    assert emit_stub_module(lowered.value) == Ok(
        "from typing import overload\n\n"
        "@overload\n"
        "def query[E, Ts1, Ts2](components_1: type[Ts1], "
        "components_2: type[Ts2], /) -> tuple[E, Ts1, Ts2] | None: ...\n"
        "@overload\n"
        "def query[E](*components: type[object]) -> "
        "tuple[E, *tuple[object, ...]] | None: ...\n"
    )


def test_preserves_unenriched_declarations_in_complete_module() -> None:
    identity = FunctionDeclaration(
        "identity",
        (Parameter("value", TypeVariable("T")),),
        TypeVariable("T"),
        ("T",),
    )
    module = StubModule("example", (identity, *variadic_module().declarations))

    lowered = lower_variadic_module(module, ArityFrontier(1, 1))

    assert isinstance(lowered, Ok)
    emitted = emit_stub_module(lowered.value)
    assert isinstance(emitted, Ok)
    assert emitted.value.startswith(
        "from typing import overload\n\ndef identity[T](value: T) -> T: ...\n\n"
    )


def test_rejects_each_on_non_variadic_parameter() -> None:
    captured = TypeVariable("T")
    invalid = StubModule(
        "example",
        (
            FunctionDeclaration(
                "combine",
                (Parameter("parser", EachType(parser_of(captured))),),
                parser_of(CollectType(captured)),
                ("T",),
            ),
        ),
    )

    result = lower_variadic_module(invalid, ArityFrontier())

    assert isinstance(result, Err)
    assert result.error.code is LoweringErrorCode.INVALID_EACH_POSITION


def test_rejects_invalid_arity_frontier_as_typed_failure() -> None:
    result = lower_variadic_module(variadic_module(), ArityFrontier(3, 2))

    assert isinstance(result, Err)
    assert result.error.code is LoweringErrorCode.INVALID_FRONTIER


def test_lowers_literal_conditional_to_precise_and_conservative_overloads() -> None:
    mode = TypeVariable("M")
    module = StubModule(
        "reader",
        (
            FunctionDeclaration(
                "read",
                (
                    Parameter("path", TypeName("str")),
                    Parameter("mode", mode),
                ),
                IfType(
                    EqualPredicate(mode, LiteralType("text")),
                    TypeName("str"),
                    TypeName("bytes"),
                ),
                ("M",),
            ),
        ),
    )

    lowered = lower_variadic_module(module, ArityFrontier())

    assert isinstance(lowered, Ok)
    assert emit_stub_module(lowered.value) == Ok(
        "from typing import Literal, overload\n\n"
        "@overload\n"
        "def read(path: str, mode: Literal['text']) -> str: ...\n"
        "@overload\n"
        "def read[M](path: str, mode: M) -> str | bytes: ...\n"
    )


def test_lowers_assignable_conditional_for_an_ordinary_type() -> None:
    item = TypeVariable("T")
    module = StubModule(
        "normalizer",
        (
            FunctionDeclaration(
                "normalize",
                (Parameter("value", item),),
                IfType(
                    AssignablePredicate(item, TypeName("str")),
                    TypeName("str"),
                    TypeName("bytes"),
                ),
                ("T",),
            ),
        ),
    )

    lowered = lower_variadic_module(module, ArityFrontier())

    assert isinstance(lowered, Ok)
    assert emit_stub_module(lowered.value) == Ok(
        "from typing import overload\n\n"
        "@overload\n"
        "def normalize(value: str) -> str: ...\n"
        "@overload\n"
        "def normalize[T](value: T) -> str | bytes: ...\n"
    )


def test_lowers_any_and_not_predicates_in_stable_order() -> None:
    item = TypeVariable("T")
    choice = AnyPredicate(
        (
            EqualPredicate(item, LiteralType("text")),
            NotPredicate(EqualPredicate(item, LiteralType("binary"))),
        )
    )
    module = StubModule(
        "chooser",
        (
            FunctionDeclaration(
                "choose",
                (Parameter("kind", item),),
                IfType(choice, TypeName("str"), TypeName("bytes")),
                ("T",),
            ),
        ),
    )

    lowered = lower_variadic_module(module, ArityFrontier())

    assert isinstance(lowered, Ok)
    assert emit_stub_module(lowered.value) == Ok(
        "from typing import Literal, overload\n\n"
        "@overload\n"
        "def choose(kind: Literal['text']) -> str: ...\n"
        "@overload\n"
        "def choose[T](kind: T) -> str | bytes: ...\n"
    )


def test_lowers_known_false_not_predicate_case() -> None:
    item = TypeVariable("T")
    module = StubModule(
        "chooser",
        (
            FunctionDeclaration(
                "choose",
                (Parameter("kind", item),),
                IfType(
                    NotPredicate(EqualPredicate(item, TypeName("bytes"))),
                    TypeName("str"),
                    TypeName("bytes"),
                ),
                ("T",),
            ),
        ),
    )

    lowered = lower_variadic_module(module, ArityFrontier())

    assert isinstance(lowered, Ok)
    assert emit_stub_module(lowered.value) == Ok(
        "from typing import overload\n\n"
        "@overload\n"
        "def choose(kind: bytes) -> bytes: ...\n"
        "@overload\n"
        "def choose[T](kind: T) -> str | bytes: ...\n"
    )


def test_lowers_known_true_all_predicate_case() -> None:
    item = TypeVariable("T")
    condition = AllPredicate(
        (
            EqualPredicate(item, TypeName("str")),
            AssignablePredicate(item, TypeName("str")),
        )
    )
    module = StubModule(
        "chooser",
        (
            FunctionDeclaration(
                "choose",
                (Parameter("kind", item),),
                IfType(condition, TypeName("str"), TypeName("bytes")),
                ("T",),
            ),
        ),
    )

    lowered = lower_variadic_module(module, ArityFrontier())

    assert isinstance(lowered, Ok)
    assert emit_stub_module(lowered.value) == Ok(
        "from typing import overload\n\n"
        "@overload\n"
        "def choose(kind: str) -> str: ...\n"
        "@overload\n"
        "def choose[T](kind: T) -> str | bytes: ...\n"
    )


def test_rejects_assignability_with_an_unrepresentable_controller_position() -> None:
    item = TypeVariable("T")
    module = StubModule(
        "normalizer",
        (
            FunctionDeclaration(
                "normalize",
                (Parameter("value", item),),
                IfType(
                    AssignablePredicate(TypeName("str"), item),
                    TypeName("str"),
                    TypeName("bytes"),
                ),
                ("T",),
            ),
        ),
    )

    lowered = lower_variadic_module(module, ArityFrontier())

    assert isinstance(lowered, Err)
    assert lowered.error.code is LoweringErrorCode.UNSUPPORTED_PREDICATE


def test_lowers_finite_map_in_declared_case_order() -> None:
    item = TypeVariable("T")
    module = StubModule(
        "serializer",
        (
            FunctionDeclaration(
                "serialize",
                (Parameter("value", item),),
                MapType(
                    item,
                    (
                        MapCase(TypeName("int"), TypeName("float")),
                        MapCase(TypeName("bytes"), TypeName("str")),
                    ),
                    item,
                ),
                ("T",),
            ),
        ),
    )

    lowered = lower_variadic_module(module, ArityFrontier())

    assert isinstance(lowered, Ok)
    assert emit_stub_module(lowered.value) == Ok(
        "from typing import overload\n\n"
        "@overload\n"
        "def serialize(value: int) -> float: ...\n"
        "@overload\n"
        "def serialize(value: bytes) -> str: ...\n"
        "@overload\n"
        "def serialize[T](value: T) -> float | str | T: ...\n"
    )


def test_rejects_duplicate_finite_map_inputs() -> None:
    item = TypeVariable("T")
    mapping = MapType(
        item,
        (
            MapCase(TypeName("int"), TypeName("str")),
            MapCase(TypeName("int"), TypeName("bytes")),
        ),
        item,
    )
    module = StubModule(
        "serializer",
        (
            FunctionDeclaration(
                "serialize",
                (Parameter("value", item),),
                mapping,
                ("T",),
            ),
        ),
    )

    lowered = lower_variadic_module(module, ArityFrontier())

    assert isinstance(lowered, Err)
    assert lowered.error.code is LoweringErrorCode.DUPLICATE_MAP_CASE
