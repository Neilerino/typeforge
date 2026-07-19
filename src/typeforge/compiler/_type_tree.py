"""Exhaustive traversal primitives for lowered type-expression trees."""

from collections.abc import Callable, Iterator
from typing import assert_never

from typeforge.compiler.lowering import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    CollectType,
    EachType,
    EqualPredicate,
    FieldType,
    FixedTuple,
    HomogeneousTuple,
    IfType,
    LiteralType,
    MapCase,
    MapFieldsType,
    MapType,
    MapValueType,
    NotPredicate,
    Predicate,
    RuntimeInputType,
    SchemaType,
    TypeApplication,
    TypeExpression,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
)

type TypeTransform = Callable[[TypeExpression], TypeExpression | None]


def rewrite_type(
    expression: TypeExpression,
    transform: TypeTransform,
) -> TypeExpression:
    """Rewrite a type tree top-down, without traversing replacements."""
    replacement = transform(expression)
    if replacement is not None:
        return replacement
    return rewrite_type_children(
        expression,
        lambda child: rewrite_type(child, transform),
    )


def rewrite_type_children(
    expression: TypeExpression,
    rewrite: Callable[[TypeExpression], TypeExpression],
) -> TypeExpression:
    """Rewrite only the immediate children of a type-expression node."""
    match expression:
        case TypeApplication(constructor, arguments):
            return TypeApplication(
                rewrite(constructor),
                tuple(rewrite(argument) for argument in arguments),
            )
        case FixedTuple(items):
            return FixedTuple(tuple(rewrite(item) for item in items))
        case HomogeneousTuple(item):
            return HomogeneousTuple(rewrite(item))
        case EachType(item):
            return EachType(rewrite(item))
        case CollectType(item):
            return CollectType(rewrite(item))
        case UnpackedType(item):
            return UnpackedType(rewrite(item))
        case UnionExpression(members):
            return UnionExpression(tuple(rewrite(member) for member in members))
        case IfType(condition, when_true, when_false):
            return IfType(
                _rewrite_predicate(condition, rewrite),
                rewrite(when_true),
                rewrite(when_false),
            )
        case MapType(subject, cases, default):
            return MapType(
                rewrite(subject),
                tuple(
                    MapCase(
                        rewrite(case.input_type),
                        rewrite(case.output_type),
                    )
                    for case in cases
                ),
                rewrite(default),
            )
        case FieldType(name, value, required, readonly):
            return FieldType(
                rewrite(name),
                rewrite(value),
                required,
                readonly,
            )
        case MapFieldsType(record, field_transform):
            return MapFieldsType(
                rewrite(record),
                rewrite(field_transform),
            )
        case SchemaType(item):
            return SchemaType(rewrite(item))
        case (
            TypeName()
            | TypeVariable()
            | LiteralType()
            | MapValueType()
            | RuntimeInputType()
        ):
            return expression
        case _ as unreachable:
            assert_never(unreachable)


def _rewrite_predicate(
    predicate: Predicate,
    rewrite: Callable[[TypeExpression], TypeExpression],
) -> Predicate:
    match predicate:
        case EqualPredicate(left, right):
            return EqualPredicate(rewrite(left), rewrite(right))
        case AssignablePredicate(source, target):
            return AssignablePredicate(rewrite(source), rewrite(target))
        case AllPredicate(predicates):
            return AllPredicate(
                tuple(_rewrite_predicate(item, rewrite) for item in predicates)
            )
        case AnyPredicate(predicates):
            return AnyPredicate(
                tuple(_rewrite_predicate(item, rewrite) for item in predicates)
            )
        case NotPredicate(item):
            return NotPredicate(_rewrite_predicate(item, rewrite))
        case _ as unreachable:
            assert_never(unreachable)


def walk_type(expression: TypeExpression) -> Iterator[TypeExpression]:
    """Yield every type-expression node in pre-order, including predicate operands."""
    yield expression
    match expression:
        case TypeApplication(constructor, arguments):
            yield from walk_type(constructor)
            for argument in arguments:
                yield from walk_type(argument)
        case FixedTuple(items):
            for item in items:
                yield from walk_type(item)
        case (
            HomogeneousTuple(item)
            | EachType(item)
            | CollectType(item)
            | UnpackedType(item)
            | SchemaType(item)
        ):
            yield from walk_type(item)
        case UnionExpression(members):
            for member in members:
                yield from walk_type(member)
        case IfType(condition, when_true, when_false):
            yield from _walk_predicate_types(condition)
            yield from walk_type(when_true)
            yield from walk_type(when_false)
        case MapType(subject, cases, default):
            yield from walk_type(subject)
            for case in cases:
                yield from walk_type(case.input_type)
                yield from walk_type(case.output_type)
            yield from walk_type(default)
        case FieldType(name, value):
            yield from walk_type(name)
            yield from walk_type(value)
        case MapFieldsType(record, transform):
            yield from walk_type(record)
            yield from walk_type(transform)
        case (
            TypeName()
            | TypeVariable()
            | LiteralType()
            | MapValueType()
            | RuntimeInputType()
        ):
            return
        case _ as unreachable:
            assert_never(unreachable)


def _walk_predicate_types(predicate: Predicate) -> Iterator[TypeExpression]:
    match predicate:
        case EqualPredicate(left, right):
            yield from walk_type(left)
            yield from walk_type(right)
        case AssignablePredicate(source, target):
            yield from walk_type(source)
            yield from walk_type(target)
        case AllPredicate(predicates) | AnyPredicate(predicates):
            for item in predicates:
                yield from _walk_predicate_types(item)
        case NotPredicate(item):
            yield from _walk_predicate_types(item)
        case _ as unreachable:
            assert_never(unreachable)
