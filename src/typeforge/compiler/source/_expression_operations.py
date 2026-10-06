"""Preserve native typing structure while keeping enriched annotations opaque."""

from collections.abc import Iterator
from dataclasses import replace

from typeforge.compiler.source._model import (
    AppliedTypeExpression,
    FieldConstructionTypeExpression,
    FieldReplacementTypeExpression,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RecordTypeExpression,
    SchemaTypeExpression,
    SourceModule,
    SourceTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
)


def annotation_expressions(module: SourceModule) -> tuple[SourceTypeExpression, ...]:
    """Collect annotation roots from every owned declaration position."""
    return (
        *(
            annotation
            for function in module.functions
            for annotation in (
                *(parameter.annotation for parameter in function.parameters),
                function.returns,
            )
            if annotation is not None
        ),
        *(
            field.annotation
            for declaration in module.typed_dicts
            for field in declaration.fields
        ),
        *(base for declaration in module.classes for base in declaration.bases),
        *(
            field.annotation
            for declaration in module.classes
            for field in declaration.fields
        ),
        *(
            annotation
            for declaration in module.classes
            for method in declaration.methods
            for annotation in (
                *(parameter.annotation for parameter in method.parameters),
                method.returns,
            )
            if annotation is not None
        ),
        *module.variable_annotations,
    )


def walk_type_expression(
    expression: SourceTypeExpression,
) -> Iterator[SourceTypeExpression]:
    """Visit the owned expression tree in authored child order."""
    yield expression
    children: tuple[SourceTypeExpression, ...]
    match expression:
        case FieldConstructionTypeExpression(name=name, value=value):
            children = (name, value)
        case FieldReplacementTypeExpression(field=field, name=name, value=value):
            children = (field, *(item for item in (name, value) if item is not None))
        case RecordTypeExpression(record=record, transform=transform):
            children = (record, transform)
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            children = (constructor, *arguments)
        case UnionTypeExpression(members=members):
            children = members
        case StarredTypeExpression(item=item):
            children = (item,)
        case (
            MarkerTypeExpression(arguments=arguments)
            | SchemaTypeExpression(arguments=arguments)
        ):
            children = arguments
        case _:
            children = ()

    for child in children:
        yield from walk_type_expression(child)


def opaque_enriched_annotations(
    expression: SourceTypeExpression,
) -> SourceTypeExpression:
    """Retain native structure for field operations with a separate Schema policy."""
    match expression:
        case NameTypeExpression() | RawTypeExpression():
            return expression
        case UnionTypeExpression(members=members):
            return replace(
                expression,
                members=tuple(opaque_enriched_annotations(item) for item in members),
            )
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return replace(
                expression,
                constructor=opaque_enriched_annotations(constructor),
                arguments=tuple(
                    opaque_enriched_annotations(item) for item in arguments
                ),
            )
        case StarredTypeExpression(item=item):
            return replace(expression, item=opaque_enriched_annotations(item))
        case _:
            return RawTypeExpression(expression.source, expression.span)
