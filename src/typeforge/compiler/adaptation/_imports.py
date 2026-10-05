"""Source annotation analysis for imports required by adaptation."""

from typing import assert_never

from typeforge.compiler.source import (
    AppliedTypeExpression,
    CaptureTypeExpression,
    DefaultMarker,
    MapMarker,
    MarkerNormalizationError,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceModule,
    SourceTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
    normalize_marker,
)
from typeforge.compiler.stub_ir import ImportFrom


def annotation_imports(module: SourceModule) -> tuple[ImportFrom, ...]:
    names: list[str] = []
    all_functions = (
        *module.functions,
        *(method for source_class in module.classes for method in source_class.methods),
    )
    if any(
        function.returns is None
        or any(parameter.annotation is None for parameter in function.parameters)
        for function in all_functions
    ):
        names.append("Any")

    if any(
        annotation_contains_default_never(function.returns)
        or any(
            annotation_contains_default_never(parameter.annotation)
            for parameter in function.parameters
        )
        for function in module.functions
    ):
        names.append("Never")

    return (ImportFrom("typing", tuple(names)),) if names else ()


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
        case (
            NameTypeExpression()
            | CaptureTypeExpression()
            | RawTypeExpression()
            | RuntimeInputTypeExpression()
        ):
            return False
        case _ as unreachable:
            assert_never(unreachable)
