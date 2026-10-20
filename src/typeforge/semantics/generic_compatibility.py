"""The deliberately finite generic compatibility rules shared by both adapters."""

from typeforge.semantics.domain.exceptions import UnsupportedExpressionSemanticError
from typeforge.semantics.domain.generics import GenericFamily, GenericType
from typeforge.semantics.protocols import TypeSystem


def generic_family(name: str) -> GenericFamily | None:
    """Recognize compiler-native names without treating arbitrary suffixes as types."""
    aliases = {
        "List": GenericFamily.LIST,
        "Set": GenericFamily.SET,
        "Dict": GenericFamily.DICT,
        "FrozenSet": GenericFamily.FROZENSET,
        "Tuple": GenericFamily.TUPLE,
    }
    for family in GenericFamily:
        if name == family.value:
            return family

        if name in {f"typing.{family.value}", f"collections.abc.{family.value}"}:
            return family

    if name.startswith("typing."):
        return aliases.get(name.removeprefix("typing."))

    return None


def compatible_generics[T](
    source: GenericType[T], target: GenericType[T], type_system: TypeSystem[T]
) -> bool:
    """Compare known families; adapters own native origins and unsupported facts."""
    if target.family is GenericFamily.SEQUENCE:
        elements = sequence_elements(source)
        if elements is None:
            return False

        _arity(target, 1)
        return all(
            type_system.assignable(item, target.arguments[0]).unwrap()
            for item in elements
        )

    if target.family is GenericFamily.MAPPING:
        if source.family not in {GenericFamily.DICT, GenericFamily.MAPPING}:
            return False

        _arity(source, 2)
        _arity(target, 2)
        return (
            _invariant(source.arguments[0], target.arguments[0], type_system)
            and type_system.assignable(
                source.arguments[1], target.arguments[1]
            ).unwrap()
        )

    if source.family is not target.family:
        return False

    if target.family is GenericFamily.TUPLE:
        if target.variadic:
            _arity(target, 1)
            return all(
                type_system.assignable(item, target.arguments[0]).unwrap()
                for item in source.arguments
            )

        if source.variadic or len(source.arguments) != len(target.arguments):
            return False

        return all(
            type_system.assignable(left, right).unwrap()
            for left, right in zip(source.arguments, target.arguments, strict=True)
        )

    _arity(source, 2 if source.family is GenericFamily.DICT else 1)
    _arity(target, len(source.arguments))
    if source.family is GenericFamily.FROZENSET:
        return type_system.assignable(source.arguments[0], target.arguments[0]).unwrap()

    return all(
        _invariant(left, right, type_system)
        for left, right in zip(source.arguments, target.arguments, strict=True)
    )


def sequence_elements[T](source: GenericType[T]) -> tuple[T, ...] | None:
    """The supported Sequence projection, shared by matching and compatibility."""
    if source.family not in {
        GenericFamily.LIST,
        GenericFamily.TUPLE,
        GenericFamily.SEQUENCE,
    }:
        return None

    if source.family is not GenericFamily.TUPLE or source.variadic:
        _arity(source, 1)

    return source.arguments


def _invariant[T](left: T, right: T, type_system: TypeSystem[T]) -> bool:
    # Mutual assignment preserves Python's gradual Any compatibility while
    # rejecting one-way subtype or numeric widening in mutable containers.
    return (
        type_system.assignable(left, right).unwrap()
        and type_system.assignable(right, left).unwrap()
    )


def _arity[T](value: GenericType[T], expected: int) -> None:
    if len(value.arguments) != expected:
        raise UnsupportedExpressionSemanticError(
            f"{value.family} requires {expected} argument(s) for generic compatibility"
        )
