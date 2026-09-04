"""Source annotation analysis for imports required by adaptation."""

import ast
from pathlib import Path
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
    static_export_names,
)
from typeforge.compiler.stub_ir import ImportFrom


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


def collect_imports(path: Path) -> tuple[ImportFrom, ...]:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(path), type_comments=True)
    exported_names = _collect_export_names(module)
    imports: list[ImportFrom] = []
    for statement in module.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        if (
            statement.level == 0
            and statement.module is not None
            and (
                statement.module == "typeforge"
                or statement.module.startswith("typeforge.")
            )
        ):
            continue
        names = tuple(
            _render_import_name(alias, exported_names) for alias in statement.names
        )
        module_name = f"{'.' * statement.level}{statement.module or ''}"
        imports.append(ImportFrom(module_name, names))
    return tuple(imports)


def _collect_export_names(module: ast.Module) -> frozenset[str]:
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        ):
            continue
        names = static_export_names(statement.value)
        return frozenset(names or ())
    return frozenset()


def _render_import_name(alias: ast.alias, exported_names: frozenset[str]) -> str:
    local_name = alias.asname or alias.name
    if alias.asname is not None or local_name in exported_names:
        return f"{alias.name} as {local_name}"
    return alias.name
