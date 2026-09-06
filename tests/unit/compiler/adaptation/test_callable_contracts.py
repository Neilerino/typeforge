from pathlib import Path
from textwrap import dedent

import pytest

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.source import SourcePosition, SourceSpan, parse_source
from typeforge.compiler.specialization import ArityFrontier, lower_variadic_module
from typeforge.compiler.stub_ir import (
    EqualPredicate,
    FunctionDeclaration,
    GeneratedElementOrigin,
    MapCase,
    MapType,
    OverloadDeclaration,
    Parameter,
    TypeApplication,
    TypeName,
    TypeVariable,
    walk_module,
)


@pytest.mark.parametrize(
    "return_annotation", ["Encoded[T]", "Map[T, Case[int, Copy[Payload]]]"]
)
def test_callable_contract_preserves_relationship_before_record_rewriting(
    return_annotation: str,
) -> None:
    source = (
        parse_source(
            dedent(f"""\
            from typing import TypedDict
            from typeforge import Case, Field, Key, Map, MapFields, Value
            class Payload(TypedDict):
                value: int
            type Copy[T] = MapFields[T, Field[Key, Value]]
            type Encoded[T] = Map[T, Case[int, Copy[Payload]]]
            def encode[T](value: T) -> {return_annotation}: ...
            def identity[T](value: T) -> T: ...
            """),
            Path("contracts.py"),
        )
        .unwrap()
        .source
    )

    adapted = adapt_source_module(source).unwrap()

    relationship, contract = adapted.reusable_elements
    assert isinstance(contract, FunctionDeclaration)
    assert contract == FunctionDeclaration(
        name="encode",
        parameters=(Parameter("value", TypeVariable("T")),),
        return_type=MapType(
            TypeVariable("T"),
            (
                MapCase(
                    TypeName("int"),
                    TypeApplication(TypeName("Copy"), (TypeName("Payload"),)),
                ),
            ),
            TypeName("Never"),
        ),
        type_parameters=("T",),
    )
    generated = adapted.declarations[-2]
    assert isinstance(generated, FunctionDeclaration)
    assert isinstance(generated.return_type, MapType)
    assert generated.return_type.cases[0].output_type == TypeName("Copy_Payload")
    assert GeneratedElementOrigin(source.functions[0].span, contract) in adapted.origins
    assert all(item.origin != source.functions[1].span for item in adapted.origins)

    for maximum_arity in (1, 3):
        specialized = lower_variadic_module(
            adapted, ArityFrontier(0, maximum_arity)
        ).unwrap()
        assert specialized.reusable_elements[0] is relationship
        assert specialized.reusable_elements[1] is contract
        overload = specialized.declarations[-2]
        assert isinstance(overload, OverloadDeclaration)
        callable_origins = tuple(
            item.generated
            for item in specialized.origins
            if item.origin == source.functions[0].span
        )
        assert len(callable_origins) == 2
        assert callable_origins[0] is overload
        assert callable_origins[1] is contract
        assert all(
            any(item.generated is element for element in walk_module(specialized))
            for item in specialized.origins
        )


def test_same_named_contracts_keep_authored_identity_and_class_type_variables() -> None:
    source = (
        parse_source(
            dedent("""\
            from typeforge import Case, Map
            class First[T]:
                def convert(self, value: T) -> Map[T, Case[int, str]]: ...
            class Second[U]:
                def convert(self, value: U) -> Map[U, Case[int, bytes]]: ...
            if enabled:
                def convert[V](value: V) -> Map[V, Case[int, bool]]: ...
            else:
                def convert[V](value: V) -> Map[V, Case[int, float]]: ...
            """),
            Path("scopes.py"),
        )
        .unwrap()
        .source
    )

    adapted = adapt_source_module(source).unwrap()
    specialized = lower_variadic_module(adapted, ArityFrontier(0, 2)).unwrap()

    assert len(specialized.reusable_elements) == 4
    expected_types = (("T", "str"), ("U", "bytes"), ("V", "bool"), ("V", "float"))
    for authored, contract, (parameter, output) in zip(
        source.functions, specialized.reusable_elements, expected_types, strict=True
    ):
        assert isinstance(contract, FunctionDeclaration)
        assert contract.name == "convert"
        assert contract.parameters[-1] == Parameter("value", TypeVariable(parameter))
        assert contract.return_type == MapType(
            TypeVariable(parameter),
            (MapCase(TypeName("int"), TypeName(output)),),
            TypeName("Never"),
        )
        assert contract.type_parameters == (() if parameter in ("T", "U") else ("V",))
        associations = tuple(
            item.origin for item in specialized.origins if item.generated is contract
        )
        assert associations == (authored.span,)

    assert adapt_source_module(source).unwrap() == adapted
    assert lower_variadic_module(adapted, ArityFrontier(0, 2)).unwrap() == specialized


def test_schema_origins_reach_retained_predicate_operands() -> None:
    path = Path("predicate.py")
    source = (
        parse_source(
            dedent("""\
            from typeforge import Case, Equal, Map
            from typeforge.pydantic import Schema
            def convert[T](value: T) -> Map[T, Case[Equal[T, Schema[int]], str]]: ...
            """),
            path,
        )
        .unwrap()
        .source
    )
    adapted = adapt_source_module(source).unwrap()

    specialized = lower_variadic_module(adapted, ArityFrontier(0, 1)).unwrap()

    contract, schema_root = specialized.reusable_elements
    assert isinstance(contract, FunctionDeclaration)
    assert isinstance(contract.return_type, MapType)
    predicate = contract.return_type.cases[0].test
    assert isinstance(predicate, EqualPredicate)
    assert predicate.right == schema_root == TypeName("int")
    assert predicate.right is not schema_root
    schema_span = SourceSpan(path, SourcePosition(3, 49), SourcePosition(3, 60))
    schema_targets = tuple(
        item.generated for item in specialized.origins if item.origin == schema_span
    )
    assert len(schema_targets) == 2
    overload = specialized.declarations[0]
    assert isinstance(overload, OverloadDeclaration)
    assert schema_targets[0] is overload.signatures[0].parameters[0].annotation
    assert schema_targets[0] is predicate.right
    assert schema_targets[1] is schema_root
