"""Relations between static types that retain unresolved identity."""

from collections.abc import Iterable
from itertools import chain

from typeforge.semantics.domain.assertions import (
    expect_possible_type,
    expect_type_value,
)
from typeforge.semantics.domain.models import (
    Condition,
    DeferredMap,
    EvaluationValue,
    IndeterminateCondition,
    IndeterminateType,
    ParameterizedTypeShape,
    ResolvedType,
    TypeSymbol,
    TypeValue,
    UnionTypeShape,
    UnresolvedType,
)
from typeforge.semantics.protocols import TypeSystem


def equal_types[T](
    left: TypeValue[T], right: TypeValue[T], type_system: TypeSystem[T]
) -> Condition:
    if isinstance(left, ResolvedType) and isinstance(right, ResolvedType):
        return type_system.equal(left.value, right.value).unwrap()

    if isinstance(left, IndeterminateType):
        return consensus(
            equal_types(item, right, type_system) for item in left.alternatives
        )

    if isinstance(right, IndeterminateType):
        return consensus(
            equal_types(left, item, type_system) for item in right.alternatives
        )

    if (
        isinstance(left, UnresolvedType)
        and isinstance(right, UnresolvedType)
        and isinstance(left.provenance, TypeSymbol)
        and left.provenance == right.provenance
    ):
        return True

    if is_symbol(left) or is_symbol(right):
        return IndeterminateCondition()

    if is_union(left) or is_union(right):
        left_members = union_members(left, type_system)
        right_members = union_members(right, type_system)
        return conjunction(
            chain(
                (
                    _union_member_equal(item, right_members, type_system)
                    for item in left_members
                ),
                (
                    _union_member_equal(item, left_members, type_system)
                    for item in right_members
                ),
            )
        )

    left_shape = inspect_type(left, type_system)
    right_shape = inspect_type(right, type_system)
    if left_shape is None or right_shape is None:
        return False

    if len(left_shape.arguments) != len(right_shape.arguments):
        return False

    return conjunction(
        (
            equal_types(a, b, type_system)
            for a, b in zip(
                (left_shape.origin, *left_shape.arguments),
                (right_shape.origin, *right_shape.arguments),
                strict=True,
            )
        )
    )


def is_symbol[T](value: TypeValue[T]) -> bool:
    return isinstance(value, UnresolvedType) and isinstance(
        value.provenance, TypeSymbol
    )


def inspect_type[T](
    value: TypeValue[T], type_system: TypeSystem[T]
) -> ParameterizedTypeShape[TypeValue[T]] | None:
    if isinstance(value, UnresolvedType):
        return (
            value.provenance
            if isinstance(value.provenance, ParameterizedTypeShape)
            else None
        )

    if isinstance(value, IndeterminateType):
        return None

    shape = type_system.inspect(value.value).unwrap()
    if shape is None:
        return None

    return ParameterizedTypeShape(
        ResolvedType(shape.origin),
        tuple(ResolvedType(item) for item in shape.arguments),
    )


def conjunction(values: Iterable[Condition]) -> Condition:
    unknown = False
    for value in values:
        if value is False:
            return False

        unknown |= isinstance(value, IndeterminateCondition)

    return IndeterminateCondition() if unknown else True


def consensus(values: Iterable[Condition]) -> Condition:
    outcomes = set(values)
    if outcomes == {True}:
        return True

    if outcomes == {False}:
        return False

    return IndeterminateCondition()


def assignable_types[T](
    source: TypeValue[T], target: TypeValue[T], type_system: TypeSystem[T]
) -> Condition:
    if isinstance(source, ResolvedType) and isinstance(target, ResolvedType):
        return type_system.assignable(source.value, target.value).unwrap()

    if isinstance(source, IndeterminateType):
        return consensus(
            assignable_types(item, target, type_system) for item in source.alternatives
        )

    if isinstance(target, IndeterminateType):
        return consensus(
            assignable_types(source, item, type_system) for item in target.alternatives
        )

    if is_union(source):
        return conjunction(
            assignable_types(item, target, type_system)
            for item in union_members(source, type_system)
        )

    if is_union(target):
        return disjunction(
            assignable_types(source, item, type_system)
            for item in union_members(target, type_system)
        )

    if equal_types(source, target, type_system) is True:
        return True

    # inspect/build provide structure, not generic variance or bound constraints.
    return IndeterminateCondition()


def indeterminate_type[T](
    outputs: tuple[EvaluationValue[T], ...], type_system: TypeSystem[T]
) -> IndeterminateType[T]:
    message = "indeterminate Map outputs must evaluate to types"
    alternatives: list[TypeValue[T]] = []
    for output in outputs:
        if isinstance(output, IndeterminateType):
            alternatives.extend(output.alternatives)
        elif isinstance(output, DeferredMap):
            alternatives.append(output.possible_output)
        else:
            alternatives.append(expect_type_value(output, message))

    bound = type_system.union(
        tuple(expect_possible_type(item, message).value for item in alternatives)
    ).unwrap()
    return IndeterminateType(ResolvedType(bound), tuple(alternatives))


def build_type[T](
    shape: ParameterizedTypeShape[TypeValue[T]], type_system: TypeSystem[T]
) -> TypeValue[T]:
    message = "parameterized type arguments must evaluate to types"
    native = ParameterizedTypeShape(
        expect_possible_type(shape.origin, message).value,
        tuple(expect_possible_type(item, message).value for item in shape.arguments),
    )
    built = type_system.build(native).unwrap()
    if all(isinstance(item, ResolvedType) for item in (shape.origin, *shape.arguments)):
        return ResolvedType(built)

    return UnresolvedType(built, shape)


def union_type[T](
    outputs: Iterable[EvaluationValue[T]], type_system: TypeSystem[T], message: str
) -> TypeValue[T]:
    members = tuple(
        output.possible_output
        if isinstance(output, DeferredMap)
        else expect_type_value(output, message)
        for output in outputs
    )
    bound = type_system.union(
        tuple(expect_possible_type(item, message).value for item in members)
    ).unwrap()
    if all(isinstance(item, ResolvedType) for item in members):
        return ResolvedType(bound)

    return UnresolvedType(bound, UnionTypeShape(members))


def merge_captures[T](
    left: TypeValue[T], right: TypeValue[T], type_system: TypeSystem[T]
) -> tuple[Condition, TypeValue[T]]:
    decision = equal_types(left, right, type_system)
    if not isinstance(decision, IndeterminateCondition):
        return decision, left

    if isinstance(right, ResolvedType):
        return decision, right

    if isinstance(left, ResolvedType):
        return decision, left

    left_shape = inspect_type(left, type_system)
    right_shape = inspect_type(right, type_system)
    if left_shape is not None and right_shape is not None:
        origin = merge_captures(left_shape.origin, right_shape.origin, type_system)[1]
        arguments = tuple(
            merge_captures(a, b, type_system)[1]
            for a, b in zip(left_shape.arguments, right_shape.arguments, strict=True)
        )
        return decision, build_type(
            ParameterizedTypeShape(origin, arguments), type_system
        )

    return decision, left


def is_union[T](value: TypeValue[T]) -> bool:
    return isinstance(value, UnresolvedType) and isinstance(
        value.provenance, UnionTypeShape
    )


def union_members[T](
    value: TypeValue[T], type_system: TypeSystem[T]
) -> tuple[TypeValue[T], ...]:
    if isinstance(value, UnresolvedType) and isinstance(
        value.provenance, UnionTypeShape
    ):
        return value.provenance.members

    if isinstance(value, ResolvedType):
        return tuple(
            ResolvedType(item)
            for item in type_system.union_members(value.value).unwrap()
        )

    return (value,)


def disjunction(values: Iterable[Condition]) -> Condition:
    unknown = False
    for value in values:
        if value is True:
            return True

        unknown |= isinstance(value, IndeterminateCondition)

    return IndeterminateCondition() if unknown else False


def _union_member_equal[T](
    value: TypeValue[T], members: tuple[TypeValue[T], ...], type_system: TypeSystem[T]
) -> Condition:
    return disjunction(equal_types(value, member, type_system) for member in members)
