"""Expand authored aliases before assigning schema and predicate roles."""

from collections.abc import Callable
from dataclasses import replace
from typing import assert_never

from returns.result import safe

from typeforge.compiler.adaptation._models import AdaptationError
from typeforge.compiler.source import (
    AppliedTypeExpression,
    CaptureTypeExpression,
    FieldConstructionTypeExpression,
    FieldReferenceTypeExpression,
    FieldReplacementTypeExpression,
    MarkerKind,
    MarkerNormalizationError,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RecordTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceTypeExpression,
    StarredTypeExpression,
    TypeAliasDeclaration,
    TypeParameterKind,
    UnionTypeExpression,
    bind_map_selector,
)


@safe(exceptions=(AdaptationError,))
def expand_schema_aliases(
    expression: SourceTypeExpression,
    aliases: tuple[TypeAliasDeclaration, ...],
    *,
    declaration: str,
    predicates_only: bool = False,
    type_parameters: tuple[str, ...] = (),
) -> SourceTypeExpression:
    """Expand aliases while preserving authored origins and lexical parameters.

    Predicate-only callers retain ordinary type aliases for their own output
    policies. Callable selectors and bounds request complete selection facts.
    """
    aliases = tuple(alias for alias in aliases if alias.name not in type_parameters)

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
                return _bind_map_selectors(
                    _rewrite_children(item, lambda child: expand(child, stack))
                )

        if predicates_only and not _is_predicate_reference(item, aliases):
            return _bind_map_selectors(
                _rewrite_children(item, lambda child: expand(child, stack))
            )

        alias = _find_alias(item, aliases)
        if alias is None:
            return _rewrite_children(item, lambda child: expand(child, stack))

        name = alias.qualified_name
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
        return expand(
            _substitute(alias.value, bindings, alias.qualified_name), (*stack, name)
        )

    try:
        return expand(expression)
    except MarkerNormalizationError as error:
        raise AdaptationError(declaration, error.source, error.message) from error


def _bind_map_selectors(item: SourceTypeExpression) -> SourceTypeExpression:
    """Bind Case selectors, leaving other entries for the existing validator."""
    if (
        not isinstance(item, MarkerTypeExpression)
        or item.marker is not MarkerKind.MAP
        or not item.arguments
    ):
        return item

    subject, *entries = item.arguments
    arguments: list[SourceTypeExpression] = [subject]
    for entry in entries:
        match entry:
            case MarkerTypeExpression(
                marker=MarkerKind.CASE, arguments=(selector, output)
            ):
                bound_selector = bind_map_selector(selector, subject)
                entry = replace(entry, arguments=(bound_selector, output))
            case _:
                pass

        arguments.append(entry)

    return replace(item, arguments=tuple(arguments))


def _is_predicate_reference(
    expression: SourceTypeExpression,
    aliases: tuple[TypeAliasDeclaration, ...],
    seen: tuple[tuple[str, ...], ...] = (),
) -> bool:
    match expression:
        case MarkerTypeExpression(marker=marker):
            return marker in {
                MarkerKind.EQUAL,
                MarkerKind.ASSIGNABLE,
                MarkerKind.ALL,
                MarkerKind.ANY,
                MarkerKind.NOT,
            }
        case (
            NameTypeExpression()
            | AppliedTypeExpression(constructor=NameTypeExpression())
        ):
            alias = _find_alias(expression, aliases)
            if alias is None or alias.qualified_name in seen:
                return False

            return _is_predicate_reference(
                alias.value, aliases, (*seen, alias.qualified_name)
            )
        case _:
            return False


def _find_alias(
    expression: NameTypeExpression | AppliedTypeExpression,
    aliases: tuple[TypeAliasDeclaration, ...],
) -> TypeAliasDeclaration | None:
    reference = (
        expression.constructor
        if isinstance(expression, AppliedTypeExpression)
        else expression
    )
    if not isinstance(reference, NameTypeExpression):
        return None

    name = reference.qualified_name or reference.name
    return next((item for item in aliases if item.qualified_name == name), None)


def _substitute(
    expression: SourceTypeExpression,
    bindings: dict[str, SourceTypeExpression],
    scope: tuple[str, ...],
) -> SourceTypeExpression:
    if (
        isinstance(expression, NameTypeExpression)
        and len(expression.name) == 1
        and expression.qualified_name in (None, (*scope, expression.name[0]))
    ):
        return bindings.get(expression.name[0], expression)

    return _rewrite_children(
        expression, lambda item: _substitute(item, bindings, scope)
    )


def _rewrite_children(
    expression: SourceTypeExpression,
    rewrite: Callable[[SourceTypeExpression], SourceTypeExpression],
) -> SourceTypeExpression:
    match expression:
        case FieldConstructionTypeExpression(name=name, value=value):
            return replace(expression, name=rewrite(name), value=rewrite(value))
        case FieldReplacementTypeExpression(field=field, name=name, value=value):
            return replace(
                expression,
                field=rewrite(field),
                name=None if name is None else rewrite(name),
                value=None if value is None else rewrite(value),
            )
        case RecordTypeExpression(record=record, transform=transform):
            return replace(
                expression, record=rewrite(record), transform=rewrite(transform)
            )
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
        case (
            NameTypeExpression()
            | CaptureTypeExpression()
            | FieldReferenceTypeExpression()
            | RawTypeExpression()
            | RuntimeInputTypeExpression()
        ):
            return expression
        case _ as unreachable:
            assert_never(unreachable)
