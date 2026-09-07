"""Convert compiler static types to typing IR using the caller's Never spelling."""

from collections.abc import Callable
from typing import assert_never

from typeforge.compiler.semantic_adapter._types import (
    NamedType,
    NeverType,
    ParameterizedType,
    StaticType,
    UnionType,
    UnpackedType,
    VariadicType,
)
from typeforge.compiler.stub_ir import (
    CollectType,
    EachType,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeVariable,
    UnionExpression,
)
from typeforge.compiler.stub_ir import UnpackedType as UnpackedExpression
from typeforge.semantics import RecordShape


def static_type_expression(
    value: StaticType,
    *,
    never_name: str,
    type_parameters: tuple[str, ...] = (),
    on_emit: Callable[[StaticType, StubTypeExpression], None] | None = None,
) -> StubTypeExpression:
    """Report emitted nodes so adaptation can retain origins after normalization."""

    def emit(value: StaticType) -> StubTypeExpression:
        return static_type_expression(
            value,
            never_name=never_name,
            type_parameters=type_parameters,
            on_emit=on_emit,
        )

    match value:
        case NamedType(name):
            generated: StubTypeExpression = (
                TypeVariable(name) if name in type_parameters else TypeName(name)
            )
        case NeverType():
            generated = TypeName(never_name)
        case ParameterizedType(origin, arguments):
            generated = TypeApplication(emit(origin), tuple(map(emit, arguments)))
        case UnpackedType(item):
            generated = UnpackedExpression(emit(item))
        case VariadicType(kind, item):
            generated = (
                EachType(emit(item)) if kind == "Each" else CollectType(emit(item))
            )
        case UnionType(members):
            generated = UnionExpression(tuple(map(emit, members)))
        case RecordShape(name=name):
            generated = TypeName(name or "object")
        case _ as unreachable:
            assert_never(unreachable)

    if on_emit is not None:
        on_emit(value, generated)

    return generated
