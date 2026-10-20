"""Interpret concrete relationship IR through the existing static type adapter."""

from returns.result import safe

from typeforge.compiler.semantic_adapter._lowering import (
    SemanticEnvironment,
    SemanticLoweringError,
)
from typeforge.compiler.semantic_adapter._types import (
    NEVER,
    NamedType,
    ParameterizedType,
    StaticType,
    is_static,
    union_of,
)
from typeforge.compiler.stub_ir import (
    FixedTuple,
    HomogeneousTuple,
    LiteralType,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    UnionExpression,
)


@safe(exceptions=(SemanticLoweringError,))
def stub_static_type(
    expression: StubTypeExpression, environment: SemanticEnvironment = ()
) -> StaticType:
    return _static_type(expression, environment)


def _static_type(
    expression: StubTypeExpression, environment: SemanticEnvironment
) -> StaticType:
    match expression:
        case TypeName("Never" | "typing.Never" | "typing_extensions.Never"):
            return NEVER
        case TypeName(name):
            bound = dict(environment).get(name)
            return bound if is_static(bound) else NamedType(name)
        case LiteralType(value):
            return ParameterizedType(NamedType("Literal"), (NamedType(repr(value)),))
        case TypeApplication(constructor, arguments):
            return ParameterizedType(
                _static_type(constructor, environment),
                tuple(_static_type(argument, environment) for argument in arguments),
            )
        case FixedTuple(items):
            tuple_items = tuple(_static_type(item, environment) for item in items)
            return ParameterizedType(NamedType("tuple"), tuple_items)
        case HomogeneousTuple(item):
            return ParameterizedType(
                NamedType("tuple"),
                (_static_type(item, environment), NamedType("...")),
            )
        case UnionExpression(members):
            return union_of(*(_static_type(member, environment) for member in members))
        case _:
            raise SemanticLoweringError(
                "a concrete input type is required for callable coverage"
            )
