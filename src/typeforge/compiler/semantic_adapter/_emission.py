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
)
from typeforge.compiler.stub_ir import (
    StubTypeExpression,
    TypeApplication,
    TypeName,
    UnionExpression,
)
from typeforge.compiler.stub_ir import UnpackedType as UnpackedExpression
from typeforge.semantics import RecordShape


def static_type_expression(
    value: StaticType,
    *,
    never_name: str,
    on_emit: Callable[[StaticType, StubTypeExpression], None] | None = None,
) -> StubTypeExpression:
    """Report emitted nodes so adaptation can retain origins after normalization."""

    def emit(value: StaticType) -> StubTypeExpression:
        return static_type_expression(value, never_name=never_name, on_emit=on_emit)

    match value:
        case NamedType(name):
            generated: StubTypeExpression = TypeName(name)
        case NeverType():
            generated = TypeName(never_name)
        case ParameterizedType(origin, arguments):
            generated = TypeApplication(emit(origin), tuple(map(emit, arguments)))
        case UnpackedType(item):
            generated = UnpackedExpression(emit(item))
        case UnionType(members):
            generated = UnionExpression(tuple(map(emit, members)))
        case RecordShape(name=name):
            generated = TypeName(name or "object")
        case _ as unreachable:
            assert_never(unreachable)

    if on_emit is not None:
        on_emit(value, generated)

    return generated
