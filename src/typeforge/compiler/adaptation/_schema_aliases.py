"""Expand authored schema aliases before assigning semantic roles."""

from collections.abc import Callable
from dataclasses import replace
from typing import assert_never

from returns.result import safe

from typeforge.compiler.adaptation._models import AdaptationError
from typeforge.compiler.source import (
    AppliedTypeExpression,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceTypeExpression,
    StarredTypeExpression,
    TypeAliasDeclaration,
    TypeParameterKind,
    UnionTypeExpression,
)


@safe(exceptions=(AdaptationError,))
def expand_schema_aliases(
    expression: SourceTypeExpression,
    aliases: tuple[TypeAliasDeclaration, ...],
    *,
    declaration: str,
) -> SourceTypeExpression:
    """Require the snapshot's alias context; keep source text and spans authored."""

    def expand(
        item: SourceTypeExpression, stack: tuple[tuple[str, ...], ...] = ()
    ) -> SourceTypeExpression:
        match item:
            case AppliedTypeExpression(
                constructor=NameTypeExpression(name=name), arguments=arguments
            ):
                pass
            case NameTypeExpression(name=name):
                arguments = ()
            case _:
                return _rewrite_children(item, lambda child: expand(child, stack))

        alias = next((alias for alias in aliases if alias.qualified_name == name), None)
        if alias is None:
            return _rewrite_children(item, lambda child: expand(child, stack))

        if name in stack:
            cycle = " -> ".join(".".join(part) for part in (*stack, name))
            raise AdaptationError(
                declaration, expression.source, f"cyclic schema alias: {cycle}"
            )

        if any(
            parameter.kind is not TypeParameterKind.TYPE_VAR
            for parameter in alias.type_parameters
        ):
            raise AdaptationError(
                declaration,
                expression.source,
                f"schema alias {alias.name} requires ordinary type parameters",
            )

        if len(arguments) != len(alias.type_parameters):
            count = len(alias.type_parameters)
            raise AdaptationError(
                declaration,
                expression.source,
                f"schema alias {alias.name} requires {count} type "
                f"argument{'s' if count != 1 else ''}; received {len(arguments)}",
            )

        arguments = tuple(expand(argument, stack) for argument in arguments)
        bindings = dict(
            zip(
                (parameter.name for parameter in alias.type_parameters),
                arguments,
                strict=True,
            )
        )
        return expand(_substitute(alias.value, bindings), (*stack, name))

    return expand(expression)


def _substitute(
    expression: SourceTypeExpression,
    bindings: dict[str, SourceTypeExpression],
) -> SourceTypeExpression:
    if isinstance(expression, NameTypeExpression) and len(expression.name) == 1:
        return bindings.get(expression.name[0], expression)

    return _rewrite_children(expression, lambda item: _substitute(item, bindings))


def _rewrite_children(
    expression: SourceTypeExpression,
    rewrite: Callable[[SourceTypeExpression], SourceTypeExpression],
) -> SourceTypeExpression:
    match expression:
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return replace(
                expression,
                constructor=rewrite(constructor),
                arguments=tuple(map(rewrite, arguments)),
            )
        case UnionTypeExpression(members=members):
            return replace(expression, members=tuple(map(rewrite, members)))
        case StarredTypeExpression(item=item):
            return replace(expression, item=rewrite(item))
        case (
            MarkerTypeExpression(arguments=arguments)
            | SchemaTypeExpression(arguments=arguments)
        ):
            return replace(expression, arguments=tuple(map(rewrite, arguments)))
        case NameTypeExpression() | RawTypeExpression() | RuntimeInputTypeExpression():
            return expression
        case _ as unreachable:
            assert_never(unreachable)
