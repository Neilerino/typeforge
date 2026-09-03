"""Adapt static types into lowering type expressions."""

from typing import assert_never

from typeforge.compiler.lowering import (
    TypeApplication,
    TypeExpression,
    TypeName,
    UnionExpression,
)
from typeforge.compiler.records import (
    NamedType,
    NeverType,
    ParameterizedType,
    StaticType,
    UnionType,
)
from typeforge.semantics import RecordShape


def static_type_expression(
    value: StaticType, *, never_name: str = "Never"
) -> TypeExpression:
    match value:
        case NamedType(name):
            return TypeName(name)
        case NeverType():
            return TypeName(never_name)
        case ParameterizedType(origin, arguments):
            return TypeApplication(
                static_type_expression(origin, never_name=never_name),
                tuple(
                    static_type_expression(argument, never_name=never_name)
                    for argument in arguments
                ),
            )
        case UnionType(members):
            return UnionExpression(
                tuple(
                    static_type_expression(member, never_name=never_name)
                    for member in members
                )
            )
        case RecordShape(name=name):
            return TypeName(name or "object")
        case _ as unreachable:
            assert_never(unreachable)
