"""Source annotation analysis for imports required by adaptation."""

from typing import assert_never

from typeforge.compiler.source import (
    AppliedTypeExpression,
    DefaultMarker,
    MapMarker,
    MarkerNormalizationError,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
    normalize_marker,
)


def annotation_contains_default_never(
    expression: SourceTypeExpression | None,
) -> bool:
    match expression:
        case None:
            return False
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return annotation_contains_default_never(constructor) or any(
                annotation_contains_default_never(argument) for argument in arguments
            )
        case (
            SchemaTypeExpression(arguments=arguments)
            | MarkerTypeExpression(arguments=arguments)
        ):
            if isinstance(expression, MarkerTypeExpression):
                try:
                    marker = normalize_marker(expression)
                except MarkerNormalizationError:
                    marker = None

                if isinstance(marker, MapMarker) and not any(
                    isinstance(entry, DefaultMarker) for entry in marker.entries
                ):
                    return True

            return any(
                annotation_contains_default_never(argument) for argument in arguments
            )
        case UnionTypeExpression(members=members):
            return any(annotation_contains_default_never(member) for member in members)
        case StarredTypeExpression(item=item):
            return annotation_contains_default_never(item)
        case NameTypeExpression() | RawTypeExpression() | RuntimeInputTypeExpression():
            return False
        case _ as unreachable:
            assert_never(unreachable)
