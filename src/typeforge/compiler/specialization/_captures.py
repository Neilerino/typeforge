"""Bind declared capture identities during callable specialization."""

from collections.abc import Mapping

from typeforge.compiler.stub_ir import (
    CaptureType,
    StubTypeExpression,
    TypeRewriteObserver,
    rewrite_type_children,
    walk_type,
)


def capture_tokens(expression: StubTypeExpression) -> frozenset[CaptureType]:
    return frozenset(
        item for item in walk_type(expression) if isinstance(item, CaptureType)
    )


def replace_captures(
    expression: StubTypeExpression,
    bindings: Mapping[CaptureType, StubTypeExpression],
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    if isinstance(expression, CaptureType):
        result = bindings.get(expression, expression)
    else:
        result = rewrite_type_children(
            expression,
            lambda child: replace_captures(child, bindings, on_rewrite=on_rewrite),
        )

    if on_rewrite is not None:
        on_rewrite(expression, result)

    return result
