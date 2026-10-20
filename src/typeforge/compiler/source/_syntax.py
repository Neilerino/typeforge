import ast
from dataclasses import dataclass
from pathlib import Path

from typeforge.compiler.source._model import (
    CaptureTypeExpression,
    SourcePosition,
    SourceSpan,
)


@dataclass(frozen=True, slots=True)
class ImportBindings:
    names: tuple[tuple[str, tuple[str, ...]], ...]
    captures: tuple[tuple[str, CaptureTypeExpression], ...] = ()


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


def capture_bindings(
    path: Path,
    statements: list[ast.stmt],
    bindings: ImportBindings,
    *,
    strict: bool,
) -> ImportBindings:
    captures = dict(bindings.captures)
    declared: set[str] = set()
    for statement in statements:
        declaration = _capture_declaration(path, statement, bindings)
        if declaration is None:
            if strict:
                raise AnnotationSyntaxError(
                    "type_function supports capture declarations "
                    "before its final return",
                    source_span(path, statement),
                )

            continue

        variable, expression = declaration
        if variable in declared:
            raise AnnotationSyntaxError(
                f"capture {variable!r} is declared more than once",
                source_span(path, statement),
            )

        declared.add(variable)
        captures[variable] = expression

    return ImportBindings(
        names=tuple(item for item in bindings.names if item[0] not in declared),
        captures=tuple(captures.items()),
    )


def _capture_declaration(
    path: Path,
    statement: ast.stmt,
    bindings: ImportBindings,
) -> tuple[str, CaptureTypeExpression] | None:
    if not (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name | ast.Attribute)
        and resolve_ast_name(statement.value.func, bindings) == ("typeforge", "Capture")
    ):
        return None

    call = statement.value
    if (
        call.keywords
        or len(call.args) != 1
        or not isinstance(call.args[0], ast.Constant)
        or not isinstance(call.args[0].value, str)
        or not call.args[0].value
    ):
        raise AnnotationSyntaxError(
            "Capture requires one nonempty literal string name", source_span(path, call)
        )

    variable = statement.targets[0].id
    span = source_span(path, statement)
    return variable, CaptureTypeExpression(
        source=variable,
        span=span,
        name=call.args[0].value,
        declaration=span,
    )


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
