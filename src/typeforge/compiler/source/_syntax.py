import ast
from dataclasses import dataclass
from pathlib import Path

from typeforge.compiler.source._model import SourcePosition, SourceSpan


@dataclass(frozen=True, slots=True)
class ImportBindings:
    names: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class AnnotationSyntaxError(Exception):
    message: str
    span: SourceSpan


def collect_import_bindings(module: ast.Module) -> ImportBindings:
    bindings: list[tuple[str, tuple[str, ...]]] = []
    for statement in module.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                local_name = alias.asname or alias.name.split(".")[0]
                qualified_name = tuple(alias.name.split("."))
                if alias.asname is None:
                    qualified_name = (qualified_name[0],)

                bindings.append((local_name, qualified_name))
        elif isinstance(statement, ast.ImportFrom) and statement.module is not None:
            module_name = tuple(statement.module.split("."))
            for alias in statement.names:
                if alias.name != "*":
                    bindings.append(
                        (alias.asname or alias.name, (*module_name, alias.name))
                    )

    return ImportBindings(names=tuple(bindings))


def expression_name(node: ast.Name | ast.Attribute) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)

    if isinstance(node.value, ast.Name | ast.Attribute):
        return (*expression_name(node.value), node.attr)

    return (node.attr,)


def resolve_name(
    name: tuple[str, ...], bindings: ImportBindings
) -> tuple[str, ...] | None:
    if not name:
        return None

    imported = dict(bindings.names).get(name[0])
    if imported is None:
        return None

    return (*imported, *name[1:])


def resolve_ast_name(
    node: ast.expr, bindings: ImportBindings
) -> tuple[str, ...] | None:
    if not isinstance(node, ast.Name | ast.Attribute):
        return None

    return resolve_name(expression_name(node), bindings)


def source_span(
    path: Path,
    node: ast.stmt
    | ast.expr
    | ast.arg
    | ast.TypeVar
    | ast.TypeVarTuple
    | ast.ParamSpec,
) -> SourceSpan:
    end_line = node.end_lineno or node.lineno
    end_column = node.end_col_offset or node.col_offset
    return SourceSpan(
        path=path,
        start=SourcePosition(line=node.lineno, column=node.col_offset),
        end=SourcePosition(line=end_line, column=end_column),
    )
