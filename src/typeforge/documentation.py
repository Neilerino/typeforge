import ast
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from inspect import cleandoc
from pathlib import Path
from typing import Protocol

from typeforge._documentation import Doc
from typeforge._result import Err, Ok, Result
from typeforge.analysis.model import SourcePosition, SourceSpan, VirtualDocument

__all__ = (
    "Doc",
    "Documentation",
    "DocumentationError",
    "DocumentationErrorCode",
    "DocumentationProvider",
    "DocumentationQuery",
    "static_documentation",
)


@dataclass(frozen=True, slots=True)
class Documentation:
    markdown: str
    path: Path
    span: SourceSpan


class DocumentationErrorCode(StrEnum):
    SYNTAX = "syntax"
    READ = "read"
    INVALID_DOC = "invalid_doc"


@dataclass(frozen=True, slots=True)
class DocumentationError:
    code: DocumentationErrorCode
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class DocumentationQuery:
    document: VirtualDocument
    position: SourcePosition
    project_root: Path
    workspace_documents: tuple[VirtualDocument, ...] = ()
    source_roots: tuple[Path, ...] = ()


class DocumentationProvider(Protocol):
    def __call__(
        self, query: DocumentationQuery
    ) -> Result[Documentation | None, DocumentationError]: ...


def static_documentation(
    query: DocumentationQuery,
) -> Result[Documentation | None, DocumentationError]:
    context = _resolution_context(query)
    module = _module_for_document(context, query.document)
    if isinstance(module, Err):
        return module
    declaration = _declaration_at(module.value, query.position)
    if declaration is not None:
        direct = _direct_documentation(declaration.expression, module.value, context)
        if isinstance(direct, Err):
            return direct
        if direct.value is not None:
            return Ok(
                Documentation(
                    direct.value,
                    module.value.path,
                    declaration.span,
                )
            )
        return Ok(None)
    reference = _reference_at(
        query.document.authored_text,
        module.value.tree,
        query.position,
        module.value,
    )
    if reference is None:
        return Ok(None)
    if isinstance(reference, _ImportedSymbol):
        return _documentation_for_target(context, reference, ())
    return _documentation_for(context, module.value, reference, ())


@dataclass(frozen=True, slots=True)
class _ImportedSymbol:
    module: str
    name: str


@dataclass(frozen=True, slots=True)
class _TypeDefinition:
    name: str
    expression: ast.expr
    span: SourceSpan
    name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class _Module:
    name: str
    path: Path
    tree: ast.Module
    imports: tuple[tuple[str, _ImportedSymbol], ...]
    module_imports: tuple[tuple[str, str], ...]
    definitions: tuple[_TypeDefinition, ...]
    declarations: tuple[_TypeDefinition, ...]


@dataclass(frozen=True, slots=True)
class _Source:
    path: Path
    text: str


@dataclass(frozen=True, slots=True)
class _ResolutionContext:
    source_roots: tuple[Path, ...]
    workspace_sources: tuple[_Source, ...]


def _resolution_context(query: DocumentationQuery) -> _ResolutionContext:
    documents = (query.document, *query.workspace_documents)
    sources = tuple(
        _Source(document.path.resolve(), document.authored_text)
        for document in documents
    )
    roots = _unique_paths(
        (
            *query.source_roots,
            query.project_root / "src",
            query.project_root,
            Path(__file__).resolve().parent.parent,
            *(Path(item) for item in sys.path if item),
        )
    )
    return _ResolutionContext(roots, sources)


def _module_for_document(
    context: _ResolutionContext, document: VirtualDocument
) -> Result[_Module, DocumentationError]:
    path = document.path.resolve()
    name = _module_name(path, context.source_roots)
    return _parse_module(name, path, document.authored_text)


def _load_module(
    context: _ResolutionContext, name: str
) -> Result[_Module | None, DocumentationError]:
    source = _find_source(context, name)
    if isinstance(source, Err):
        return source
    if source.value is None:
        return Ok(None)
    parsed = _parse_module(name, source.value.path, source.value.text)
    if isinstance(parsed, Err):
        return parsed
    return Ok(parsed.value)


def _documentation_for(
    context: _ResolutionContext,
    module: _Module,
    symbol: str,
    visited: tuple[tuple[Path, str], ...],
) -> Result[Documentation | None, DocumentationError]:
    key = (module.path, symbol)
    if key in visited:
        return Ok(None)
    next_visited = (*visited, key)
    definition = _definition(module.definitions, symbol)
    if definition is not None:
        direct = _direct_documentation(definition.expression, module, context)
        if isinstance(direct, Err):
            return direct
        if direct.value is not None:
            return Ok(Documentation(direct.value, module.path, definition.span))
    imported = _lookup(module.imports, symbol)
    if imported is not None:
        return _documentation_for_target(context, imported, next_visited)
    return Ok(None)


def _documentation_for_target(
    context: _ResolutionContext,
    target: _ImportedSymbol,
    visited: tuple[tuple[Path, str], ...],
) -> Result[Documentation | None, DocumentationError]:
    loaded = _load_module(context, target.module)
    if isinstance(loaded, Err):
        return loaded
    if loaded.value is None:
        return Ok(None)
    return _documentation_for(context, loaded.value, target.name, visited)


def _is_special_form(
    context: _ResolutionContext,
    expression: ast.expr,
    module: _Module,
    name: str,
    visited: tuple[_ImportedSymbol, ...] = (),
) -> bool:
    target = _expression_symbol(expression, module)
    if target is None:
        return isinstance(expression, ast.Name) and expression.id == name
    if target in visited:
        return False
    if target.name != name:
        loaded = _load_module(context, target.module)
        if isinstance(loaded, Err) or loaded.value is None:
            return False
        definition = _definition(loaded.value.definitions, target.name)
        if definition is None:
            imported = _lookup(loaded.value.imports, target.name)
            if imported is None:
                return False
            return _target_is_special_form(context, imported, name, (*visited, target))
        return _is_special_form(
            context,
            definition.expression,
            loaded.value,
            name,
            (*visited, target),
        )
    return target.module in _SPECIAL_FORM_MODULES


def _target_is_special_form(
    context: _ResolutionContext,
    target: _ImportedSymbol,
    name: str,
    visited: tuple[_ImportedSymbol, ...],
) -> bool:
    if target.name == name and target.module in _SPECIAL_FORM_MODULES:
        return True
    loaded = _load_module(context, target.module)
    if isinstance(loaded, Err) or loaded.value is None:
        return False
    definition = _definition(loaded.value.definitions, target.name)
    if definition is not None:
        return _is_special_form(
            context, definition.expression, loaded.value, name, visited
        )
    imported = _lookup(loaded.value.imports, target.name)
    if imported is None or imported in visited:
        return False
    return _target_is_special_form(context, imported, name, (*visited, imported))


def _find_source(
    context: _ResolutionContext, name: str
) -> Result[_Source | None, DocumentationError]:
    relative = Path(*name.split("."))
    candidates = tuple(
        candidate
        for root in context.source_roots
        for candidate in (root / f"{relative}.py", root / relative / "__init__.py")
    )
    workspace = {source.path: source for source in context.workspace_sources}
    for candidate in candidates:
        resolved = candidate.resolve()
        buffered = workspace.get(resolved)
        if buffered is not None:
            return Ok(buffered)
        try:
            if resolved.is_file():
                return Ok(_Source(resolved, resolved.read_text(encoding="utf-8")))
        except OSError as error:
            return Err(
                DocumentationError(
                    DocumentationErrorCode.READ,
                    resolved,
                    str(error),
                )
            )
    return Ok(None)


_SPECIAL_FORM_MODULES = frozenset(
    {"typeforge", "typeforge._documentation", "typing", "typing_extensions"}
)


def _parse_module(
    name: str, path: Path, source: str
) -> Result[_Module, DocumentationError]:
    try:
        tree = ast.parse(source, filename=str(path), type_comments=True)
    except SyntaxError as error:
        return Err(
            DocumentationError(
                DocumentationErrorCode.SYNTAX,
                path,
                error.msg,
            )
        )
    imports, module_imports = _imports(tree, name, path.name == "__init__.py")
    definitions, declarations = _definitions(tree, source)
    return Ok(
        _Module(
            name=name,
            path=path,
            tree=tree,
            imports=imports,
            module_imports=module_imports,
            definitions=definitions,
            declarations=declarations,
        )
    )


def _imports(
    tree: ast.Module, module_name: str, is_package: bool
) -> tuple[tuple[tuple[str, _ImportedSymbol], ...], tuple[tuple[str, str], ...]]:
    symbols: dict[str, _ImportedSymbol] = {}
    modules: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                local = alias.asname or alias.name.split(".")[0]
                modules[local] = alias.name if alias.asname else local
        elif isinstance(statement, ast.ImportFrom):
            imported_module = _absolute_import_module(
                module_name,
                is_package,
                statement.module,
                statement.level,
            )
            if imported_module is None:
                continue
            for alias in statement.names:
                if alias.name == "*":
                    continue
                symbols[alias.asname or alias.name] = _ImportedSymbol(
                    imported_module, alias.name
                )
    return tuple(symbols.items()), tuple(modules.items())


def _absolute_import_module(
    current: str,
    is_package: bool,
    imported: str | None,
    level: int,
) -> str | None:
    if level == 0:
        return imported
    package = current.split(".") if is_package else current.split(".")[:-1]
    keep = len(package) - level + 1
    if keep < 0:
        return None
    parts = package[:keep]
    if imported:
        parts.extend(imported.split("."))
    return ".".join(parts)


def _definitions(
    tree: ast.Module, source: str
) -> tuple[tuple[_TypeDefinition, ...], tuple[_TypeDefinition, ...]]:
    definitions = tuple(
        definition
        for statement in tree.body
        if (definition := _statement_definition(statement, source)) is not None
    )
    declarations: list[_TypeDefinition] = []
    for node in ast.walk(tree):
        declaration = _declaration(node, source)
        if declaration is not None:
            declarations.append(declaration)
    return definitions, tuple(declarations)


def _statement_definition(statement: ast.stmt, source: str) -> _TypeDefinition | None:
    if isinstance(statement, ast.TypeAlias):
        return _type_definition(
            statement.name.id,
            statement.value,
            statement,
            statement.name,
            source,
        )
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
        if isinstance(target, ast.Name):
            return _type_definition(
                target.id, statement.value, statement, target, source
            )
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        expression = (
            statement.value
            if statement.value is not None
            and _looks_like_type_alias(statement.annotation)
            else statement.annotation
        )
        return _type_definition(
            statement.target.id,
            expression,
            statement,
            statement.target,
            source,
        )
    return None


def _declaration(node: ast.AST, source: str) -> _TypeDefinition | None:
    if isinstance(node, ast.stmt):
        return _statement_definition(node, source)
    if isinstance(node, ast.arg) and node.annotation is not None:
        return _type_definition(
            node.arg,
            node.annotation,
            node,
            node,
            source,
        )
    return None


def _type_definition(
    name: str,
    expression: ast.expr,
    declaration: ast.stmt | ast.arg,
    name_node: ast.expr | ast.arg,
    source: str,
) -> _TypeDefinition:
    return _TypeDefinition(
        name,
        expression,
        _node_span(source, declaration),
        _name_span(source, name_node, name),
    )


def _looks_like_type_alias(expression: ast.expr) -> bool:
    return (isinstance(expression, ast.Name) and expression.id == "TypeAlias") or (
        isinstance(expression, ast.Attribute) and expression.attr == "TypeAlias"
    )


def _direct_documentation(
    expression: ast.expr,
    module: _Module,
    context: _ResolutionContext,
) -> Result[str | None, DocumentationError]:
    if not isinstance(expression, ast.Subscript) or not _is_special_form(
        context, expression.value, module, "Annotated"
    ):
        return Ok(None)
    elements = (
        expression.slice.elts
        if isinstance(expression.slice, ast.Tuple)
        else [expression.slice]
    )
    nested = _direct_documentation(elements[0], module, context)
    if isinstance(nested, Err):
        return nested
    documentation = nested.value
    for metadata in elements[1:]:
        if not isinstance(metadata, ast.Call) or not _is_special_form(
            context, metadata.func, module, "Doc"
        ):
            continue
        value = _doc_argument(metadata)
        if value is None:
            return Err(
                DocumentationError(
                    DocumentationErrorCode.INVALID_DOC,
                    module.path,
                    "Doc metadata requires one string literal",
                )
            )
        documentation = value
    return Ok(documentation)


def _doc_argument(call: ast.Call) -> str | None:
    value: ast.expr | None = None
    if len(call.args) == 1 and not call.keywords:
        value = call.args[0]
    elif not call.args and len(call.keywords) == 1:
        keyword = call.keywords[0]
        if keyword.arg == "documentation":
            value = keyword.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return cleandoc(value.value)
    return None


def _expression_symbol(expression: ast.expr, module: _Module) -> _ImportedSymbol | None:
    if isinstance(expression, ast.Name):
        imported = _lookup(module.imports, expression.id)
        return imported or _ImportedSymbol(module.name, expression.id)
    if isinstance(expression, ast.Attribute):
        imported_module = _module_expression(expression.value, module)
        if imported_module is not None:
            return _ImportedSymbol(imported_module, expression.attr)
    return None


def _module_expression(expression: ast.expr, module: _Module) -> str | None:
    if isinstance(expression, ast.Name):
        imported_module = _lookup(module.module_imports, expression.id)
        if imported_module is not None:
            return imported_module
        imported_symbol = _lookup(module.imports, expression.id)
        if imported_symbol is not None:
            return f"{imported_symbol.module}.{imported_symbol.name}"
        return None
    if isinstance(expression, ast.Attribute):
        parent = _module_expression(expression.value, module)
        if parent is not None:
            return f"{parent}.{expression.attr}"
    return None


def _reference_at(
    source: str,
    tree: ast.Module,
    position: SourcePosition,
    module: _Module,
) -> str | _ImportedSymbol | None:
    lines = source.splitlines()
    if position.line < 0 or position.line >= len(lines):
        return None
    line = lines[position.line]
    column = min(max(position.column, 0), len(line))
    match = next(
        (
            item
            for item in re.finditer(r"[A-Za-z_]\w*", line)
            if item.start() <= column <= item.end()
        ),
        None,
    )
    if match is None:
        return None
    symbol = match.group()
    byte_column = len(line[: match.start()].encode("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _attribute_contains(
            node, position.line, byte_column
        ):
            return _expression_symbol(node, module)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Name, ast.alias)):
            continue
        start = getattr(node, "col_offset", -1)
        end = getattr(node, "end_col_offset", -1)
        node_line = getattr(node, "lineno", 0) - 1
        if node_line == position.line and start <= byte_column <= end:
            return symbol
    return None


def _attribute_contains(node: ast.Attribute, line: int, byte_column: int) -> bool:
    end_line = getattr(node, "end_lineno", 0) - 1
    end_column = getattr(node, "end_col_offset", -1)
    attribute_start = end_column - len(node.attr.encode("utf-8"))
    return end_line == line and attribute_start <= byte_column <= end_column


def _declaration_at(
    module: _Module, position: SourcePosition
) -> _TypeDefinition | None:
    return next(
        (
            declaration
            for declaration in module.declarations
            if _span_contains(declaration.name_span, position)
        ),
        None,
    )


def _span_contains(span: SourceSpan, position: SourcePosition) -> bool:
    return span.start <= position <= span.end


def _definition(
    definitions: tuple[_TypeDefinition, ...], name: str
) -> _TypeDefinition | None:
    return next((item for item in reversed(definitions) if item.name == name), None)


def _lookup[T](bindings: tuple[tuple[str, T], ...], name: str) -> T | None:
    return next((value for key, value in reversed(bindings) if key == name), None)


def _node_span(source: str, node: ast.stmt | ast.expr | ast.arg) -> SourceSpan:
    lines = source.splitlines(keepends=True)
    start_line = max(getattr(node, "lineno", 1) - 1, 0)
    end_line = max(getattr(node, "end_lineno", start_line + 1) - 1, 0)
    start_column = _codepoint_column(lines, start_line, node.col_offset)
    end_column = _codepoint_column(
        lines, end_line, getattr(node, "end_col_offset", node.col_offset)
    )
    start_offset = sum(len(line) for line in lines[:start_line]) + start_column
    end_offset = sum(len(line) for line in lines[:end_line]) + end_column
    return SourceSpan(
        SourcePosition(start_offset, start_line, start_column),
        SourcePosition(end_offset, end_line, end_column),
    )


def _name_span(source: str, node: ast.expr | ast.arg, name: str) -> SourceSpan:
    span = _node_span(source, node)
    end = SourcePosition(
        offset=span.start.offset + len(name),
        line=span.start.line,
        column=span.start.column + len(name),
    )
    return SourceSpan(span.start, end)


def _codepoint_column(lines: list[str], line: int, byte_column: int) -> int:
    if line >= len(lines):
        return 0
    return len(lines[line].encode("utf-8")[:byte_column].decode("utf-8"))


def _module_name(path: Path, roots: tuple[Path, ...]) -> str:
    for root in roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        parts = list(relative.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)
    return path.stem


def _unique_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return tuple(unique)
