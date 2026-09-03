"""Exhaustive traversal primitives for source type-expression trees."""

from collections.abc import Callable
from typing import assert_never

from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
)
from typeforge.compiler.model import (
    TypeExpression as SourceTypeExpression,
)


def rewrite_source_type_children(
    expression: SourceTypeExpression,
    rewrite: Callable[[SourceTypeExpression], SourceTypeExpression],
) -> SourceTypeExpression:
    """Rewrite only the immediate children of a source type-expression node."""
    match expression:
        case AppliedTypeExpression(
            source=source,
            span=span,
            constructor=constructor,
            arguments=arguments,
        ):
            return AppliedTypeExpression(
                source=source,
                span=span,
                constructor=rewrite(constructor),
                arguments=tuple(rewrite(argument) for argument in arguments),
            )
        case UnionTypeExpression(source=source, span=span, members=members):
            return UnionTypeExpression(
                source=source,
                span=span,
                members=tuple(rewrite(member) for member in members),
            )
        case StarredTypeExpression(source=source, span=span, item=item):
            return StarredTypeExpression(
                source=source,
                span=span,
                item=rewrite(item),
            )
        case MarkerTypeExpression(
            source=source,
            span=span,
            marker=marker,
            arguments=arguments,
        ):
            return MarkerTypeExpression(
                source=source,
                span=span,
                marker=marker,
                arguments=tuple(rewrite(argument) for argument in arguments),
            )
        case SchemaTypeExpression(source=source, span=span, arguments=arguments):
            return SchemaTypeExpression(
                source=source,
                span=span,
                arguments=tuple(rewrite(argument) for argument in arguments),
            )
        case NameTypeExpression() | RawTypeExpression() | RuntimeInputTypeExpression():
            return expression
        case _ as unreachable:
            assert_never(unreachable)
