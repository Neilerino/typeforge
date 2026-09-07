"""Slice 4 model contracts; evaluation of these values belongs to slice 5."""

from dataclasses import FrozenInstanceError, replace

import pytest

from typeforge import semantics


def test_type_symbols_preserve_scope_independently_of_backend_spelling() -> None:
    payload_parameter = semantics.TypeSymbol(scope=("models", "Payload"), name="T")
    same_parameter = semantics.TypeSymbol(scope=("models", "Payload"), name="T")
    other_parameter = semantics.TypeSymbol(scope=("models", "Payload"), name="U")
    other_scope = semantics.TypeSymbol(scope=("models", "Envelope"), name="T")
    other_module = semantics.TypeSymbol(scope=("other_models", "Payload"), name="T")

    assert (
        len(
            {
                payload_parameter,
                same_parameter,
                other_parameter,
                other_scope,
                other_module,
            }
        )
        == 4
    )
    assert semantics.UnresolvedType("T", payload_parameter) == semantics.UnresolvedType(
        "T", same_parameter
    )
    assert semantics.UnresolvedType("T", payload_parameter) != semantics.UnresolvedType(
        "T", other_scope
    )


def test_parameterized_provenance_retains_resolved_and_unresolved_positions() -> None:
    parameter = semantics.UnresolvedType(
        "T", semantics.TypeSymbol(scope=("models", "Payload"), name="T")
    )
    nested = semantics.UnresolvedType(
        "list[T]",
        semantics.ParameterizedTypeShape[semantics.TypeValue[str]](
            origin=semantics.ResolvedType("list"),
            arguments=(parameter,),
        ),
    )
    value = semantics.UnresolvedType(
        "tuple[int, list[T]]",
        semantics.ParameterizedTypeShape[semantics.TypeValue[str]](
            origin=semantics.ResolvedType("tuple"),
            arguments=(semantics.ResolvedType("int"), nested),
        ),
    )

    shape = value.provenance
    assert isinstance(shape, semantics.ParameterizedTypeShape)
    assert shape.origin == semantics.ResolvedType("tuple")
    known, unknown = shape.arguments
    assert known == semantics.ResolvedType("int")
    assert isinstance(unknown, semantics.UnresolvedType)
    assert isinstance(unknown.provenance, semantics.ParameterizedTypeShape)
    assert unknown.provenance.origin == semantics.ResolvedType("list")
    assert unknown.provenance.arguments == (parameter,)


def test_nested_values_distinguish_a_possible_union_from_a_definite_union() -> None:
    parameter = semantics.UnresolvedType(
        "T", semantics.TypeSymbol(scope=("models", "Payload"), name="T")
    )
    selection = semantics.IndeterminateType(
        possible_output=semantics.ResolvedType("T | str"),
        alternatives=(parameter, semantics.ResolvedType("str")),
    )
    nested = semantics.UnresolvedType(
        "tuple[T | str]",
        semantics.ParameterizedTypeShape[semantics.TypeValue[str]](
            origin=semantics.ResolvedType("tuple"), arguments=(selection,)
        ),
    )

    assert isinstance(nested.provenance, semantics.ParameterizedTypeShape)
    (argument,) = nested.provenance.arguments
    assert isinstance(argument, semantics.IndeterminateType)
    assert argument.possible_output == semantics.ResolvedType("T | str")
    assert argument.alternatives == (parameter, semantics.ResolvedType("str"))
    assert len({argument, semantics.ResolvedType("T | str")}) == 2
    assert len({nested, semantics.ResolvedType("tuple[T | str]")}) == 2


def test_unresolved_static_identity_is_distinct_from_runtime_input_and_none() -> None:
    symbol = semantics.TypeSymbol(scope=("models", "Payload"), name="T")
    unresolved = semantics.UnresolvedType[object](None, symbol)

    assert (
        len({unresolved, semantics.InputReference(), semantics.ResolvedType(None)}) == 3
    )
    assert unresolved.provenance == symbol
    assert unresolved.value is None


def test_static_type_provenance_is_immutable_and_survives_backend_replacement() -> None:
    symbol = semantics.TypeSymbol(scope=("models", "Payload"), name="T")
    unresolved = semantics.UnresolvedType("T", symbol)
    selection = semantics.IndeterminateType(
        possible_output=semantics.ResolvedType("T | str"),
        alternatives=(unresolved, semantics.ResolvedType("str")),
    )

    renamed = replace(unresolved, value="_T")
    emitted = replace(selection, possible_output=semantics.ResolvedType("_T | str"))

    assert renamed.provenance is symbol
    assert emitted.alternatives is selection.alternatives
    with pytest.raises(FrozenInstanceError):
        symbol.name = "U"  # type: ignore[misc]  # Exercise mutation rejection.

    with pytest.raises(FrozenInstanceError):
        unresolved.value = "U"  # type: ignore[misc]  # Exercise mutation rejection.

    with pytest.raises(FrozenInstanceError):
        selection.alternatives = ()  # type: ignore[misc]  # Exercise mutation rejection.
