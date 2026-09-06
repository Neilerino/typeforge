"""Exhaustive traversal primitives for lowered type-expression trees."""

from collections.abc import Callable, Iterator
from typing import assert_never

from typeforge.compiler.stub_ir._model import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    ClassDeclaration,
    CollectType,
    Declaration,
    EachType,
    EqualPredicate,
    FieldType,
    FixedTuple,
    FunctionDeclaration,
    GeneratedElement,
    HomogeneousTuple,
    LiteralType,
    MapCase,
    MapFieldsType,
    MapType,
    MapValueType,
    NotPredicate,
    OverloadDeclaration,
    Predicate,
    RuntimeInputType,
    SchemaType,
    StubTypeExpression,
    TypeAliasDeclaration,
    TypeApplication,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    VariableDeclaration,
    is_predicate,
)

type TypeRewriteObserver = Callable[[StubTypeExpression, StubTypeExpression], None]


type TypeTransform = Callable[[StubTypeExpression], StubTypeExpression | None]


def substitute_type(
    expression: StubTypeExpression,
    variable: str,
    replacement: StubTypeExpression,
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    target = TypeVariable(variable)
    return rewrite_type(
        expression,
        lambda current: replacement if current == target else None,
        on_rewrite=on_rewrite,
    )


def rewrite_type(
    expression: StubTypeExpression,
    transform: TypeTransform,
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    """Rewrite a type tree top-down, without traversing replacements."""
    replacement = transform(expression)
    if replacement is None:
        replacement = rewrite_type_children(
            expression,
            lambda child: rewrite_type(child, transform, on_rewrite=on_rewrite),
        )

    if on_rewrite is not None:
        on_rewrite(expression, replacement)

    return replacement


def rewrite_type_children(
    expression: StubTypeExpression,
    rewrite: Callable[[StubTypeExpression], StubTypeExpression],
) -> StubTypeExpression:
    """Rewrite immediate children, retaining the node when no child changes."""
    changed = False

    def rewrite_child(child: StubTypeExpression) -> StubTypeExpression:
        nonlocal changed
        replacement = rewrite(child)
        changed = changed or replacement is not child
        return replacement

    replacement = _rewrite_type_children(expression, rewrite_child)
    return replacement if changed else expression


def _rewrite_type_children(
    expression: StubTypeExpression,
    rewrite: Callable[[StubTypeExpression], StubTypeExpression],
) -> StubTypeExpression:
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
        case MapType(subject, cases, default):
            return MapType(
                rewrite(subject),
                tuple(
                    MapCase(
                        _rewrite_predicate(case.test, rewrite)
                        if is_predicate(case.test)
                        else rewrite(case.test),
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
    rewrite: Callable[[StubTypeExpression], StubTypeExpression],
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


def walk_type(expression: StubTypeExpression) -> Iterator[StubTypeExpression]:
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

        case MapType(subject, cases, default):
            yield from walk_type(subject)
            for case in cases:
                if is_predicate(case.test):
                    yield from _walk_predicate_types(case.test)
                else:
                    yield from walk_type(case.test)

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


def _walk_predicate_types(predicate: Predicate) -> Iterator[StubTypeExpression]:
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


def walk_declaration(declaration: Declaration) -> Iterator[GeneratedElement]:
    """Yield a declaration and its nested declarations and type expressions."""
    yield declaration
    match declaration:
        case FunctionDeclaration(parameters=parameters, return_type=return_type):
            for parameter in parameters:
                yield from walk_type(parameter.annotation)

            yield from walk_type(return_type)
        case OverloadDeclaration(signatures=signatures, fallback=fallback):
            for signature in (*signatures, fallback):
                yield from walk_declaration(signature)
        case ClassDeclaration(bases=bases, fields=fields, methods=methods):
            for base in bases:
                yield from walk_type(base)

            for field in fields:
                yield from walk_type(field.annotation)

            for method in methods:
                yield from walk_declaration(method)
        case (
            TypeAliasDeclaration(value=expression)
            | VariableDeclaration(annotation=expression)
        ):
            yield from walk_type(expression)
        case _ as unreachable:
            assert_never(unreachable)
