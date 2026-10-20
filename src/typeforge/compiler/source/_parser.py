import ast
from dataclasses import dataclass
from pathlib import Path

from returns.result import Failure, Result, Success

from typeforge.compiler.source._annotations import (
    parse_annotation,
    parse_type_alias,
    parse_type_parameter,
    unwrap_annotated,
)
from typeforge.compiler.source._model import (
    ClassDeclaration,
    ClassField,
    FunctionDeclaration,
    IdentifierOccurrence,
    Parameter,
    ParameterKind,
    ReturnSite,
    SourceModule,
    SourcePosition,
    SourceSpan,
    SourceTypeExpression,
    TypedDictDeclaration,
    TypedDictField,
)
from typeforge.compiler.source._syntax import (
    AnnotationSyntaxError,
    ImportBindings,
    capture_bindings,
    collect_import_bindings,
    expression_name,
    resolve_ast_name,
    source_span,
)
from typeforge.compiler.source._type_functions import (
    is_type_function,
    parse_type_function,
)


@dataclass(frozen=True, slots=True)
class SourceReadError:
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class SourceSyntaxError:
    path: Path
    message: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ParsedSource:
    """Compiler-internal syntax and the public facts from the same parse."""

    source: SourceModule
    tree: ast.Module


type FrontendError = SourceReadError | SourceSyntaxError


def parse_module(path: Path) -> Result[ParsedSource, FrontendError]:
    source = _read_source(path)
    if isinstance(source, Failure):
        return source

    return parse_source(source.unwrap(), path)


def parse_source(
    source: str, path: Path = Path("<memory>")
) -> Result[ParsedSource, SourceSyntaxError]:
    try:
        return Success(_parse_source(source, path))
    except SyntaxError as error:
        return Failure(_syntax_error(path, error))
    except AnnotationSyntaxError as error:
        return Failure(SourceSyntaxError(path, error.message, error.span))


def _parse_source(source: str, path: Path) -> ParsedSource:
    tree = ast.parse(source, filename=str(path), type_comments=True)
    bindings = capture_bindings(
        path, tree.body, collect_import_bindings(tree), strict=False
    )
    scoped_statements = _scoped_statements(tree)
    functions = tuple(
        _parse_function(path, source, node, scope, bindings)
        for node, scope in scoped_statements
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not is_type_function(node, bindings)
    )
    aliases = tuple(
        parse_type_alias(path, source, node, scope, bindings)
        for node, scope in scoped_statements
        if isinstance(node, ast.TypeAlias)
    ) + tuple(
        parse_type_function(path, source, node, scope, bindings)
        for node, scope in scoped_statements
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and is_type_function(node, bindings)
    )
    typed_dicts = _parse_typed_dicts(path, source, scoped_statements, bindings)
    classes = _parse_classes(path, source, tree, bindings, typed_dicts)
    field_spans = {field.span for record in typed_dicts for field in record.fields}
    field_spans.update(
        field.span for declaration in classes for field in declaration.fields
    )
    variable_annotations: list[SourceTypeExpression] = []
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.AnnAssign)
            or source_span(path, node) in field_spans
        ):
            continue

        annotation = parse_annotation(path, source, node.annotation, bindings)
        variable_annotations.append(annotation)

    located_nodes = sorted(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Return | ast.Name | ast.arg)
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    facts = SourceModule(
        path=path,
        functions=functions,
        aliases=aliases,
        typed_dicts=typed_dicts,
        classes=classes,
        variable_annotations=tuple(variable_annotations),
        captures=bindings.captures,
        text=source,
        docstring_span=_docstring_span(path, tree),
        future_import_spans=_future_import_spans(path, tree),
        return_sites=tuple(
            ReturnSite(
                statement=source_span(path, node),
                expression=source_span(path, node.value)
                if node.value is not None
                else None,
            )
            for node in located_nodes
            if isinstance(node, ast.Return)
        ),
        identifiers=tuple(
            IdentifierOccurrence(
                name=node.id if isinstance(node, ast.Name) else node.arg,
                span=source_span(path, node),
            )
            for node in located_nodes
            if isinstance(node, ast.Name | ast.arg)
        ),
    )
    return ParsedSource(source=facts, tree=tree)


def _docstring_span(path: Path, tree: ast.Module) -> SourceSpan | None:
    if tree.body:
        first = tree.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            return source_span(path, first)

    return None


def _future_import_spans(path: Path, tree: ast.Module) -> tuple[SourceSpan, ...]:
    start = 1 if _docstring_span(path, tree) is not None else 0
    spans: list[SourceSpan] = []
    for statement in tree.body[start:]:
        if (
            not isinstance(statement, ast.ImportFrom)
            or statement.module != "__future__"
        ):
            break

        spans.append(source_span(path, statement))

    return tuple(spans)


def _read_source(path: Path) -> Result[str, SourceReadError]:
    try:
        return Success(path.read_text(encoding="utf-8"))
    except OSError as error:
        return Failure(SourceReadError(path=path, message=str(error)))


def _syntax_error(path: Path, error: SyntaxError) -> SourceSyntaxError:
    line = error.lineno or 1
    column = max((error.offset or 1) - 1, 0)
    end_line = error.end_lineno or line
    end_column = max((error.end_offset or column + 1) - 1, column)
    span = SourceSpan(
        path=path,
        start=SourcePosition(line=line, column=column),
        end=SourcePosition(line=end_line, column=end_column),
    )
    return SourceSyntaxError(path=path, message=error.msg, span=span)


def _scoped_statements(
    module: ast.Module,
) -> tuple[tuple[ast.stmt, tuple[str, ...]], ...]:
    found: list[tuple[ast.stmt, tuple[str, ...]]] = []

    def visit_statements(statements: list[ast.stmt], scope: tuple[str, ...]) -> None:
        for statement in statements:
            found.append((statement, scope))
            if isinstance(statement, ast.ClassDef):
                visit_statements(statement.body, (*scope, statement.name))
            elif isinstance(statement, ast.If | ast.While | ast.For | ast.AsyncFor):
                visit_statements(statement.body, scope)
                visit_statements(statement.orelse, scope)
            elif isinstance(statement, ast.Try | ast.TryStar):
                visit_statements(statement.body, scope)
                for handler in statement.handlers:
                    visit_statements(handler.body, scope)

                visit_statements(statement.orelse, scope)
                visit_statements(statement.finalbody, scope)
            elif isinstance(statement, ast.With | ast.AsyncWith):
                visit_statements(statement.body, scope)
            elif isinstance(statement, ast.Match):
                for case in statement.cases:
                    visit_statements(case.body, scope)

    visit_statements(module.body, ())
    return tuple(found)


def _parse_function(
    path: Path,
    source: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    scope: tuple[str, ...],
    bindings: ImportBindings,
) -> FunctionDeclaration:
    return FunctionDeclaration(
        name=node.name,
        qualified_name=(*scope, node.name),
        parameters=_parse_parameters(path, source, node.args, bindings),
        returns=parse_annotation(path, source, node.returns, bindings),
        type_parameters=tuple(
            parse_type_parameter(path, source, parameter, bindings)
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec)
        ),
        span=source_span(path, node),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        decorators=tuple(ast.unparse(item) for item in node.decorator_list),
        decorator_spans=tuple(source_span(path, item) for item in node.decorator_list),
        body_span=SourceSpan(
            path=path,
            start=source_span(path, node.body[0]).start,
            end=source_span(path, node.body[-1]).end,
        ),
    )


def _parse_classes(
    path: Path,
    source: str,
    module: ast.Module,
    bindings: ImportBindings,
    typed_dicts: tuple[TypedDictDeclaration, ...],
) -> tuple[ClassDeclaration, ...]:
    typed_dict_names = {item.name for item in typed_dicts}
    return tuple(
        _parse_class(path, source, statement, bindings)
        for statement in module.body
        if isinstance(statement, ast.ClassDef)
        and statement.name not in typed_dict_names
    )


def _parse_class(
    path: Path,
    source: str,
    node: ast.ClassDef,
    bindings: ImportBindings,
) -> ClassDeclaration:
    fields = tuple(
        _parse_class_field(path, source, statement, bindings)
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
    )
    methods = tuple(
        _parse_function(path, source, statement, (node.name,), bindings)
        for statement in node.body
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
    )
    bases = tuple(parse_annotation(path, source, base, bindings) for base in node.bases)
    keywords = tuple(
        f"{keyword.arg}={ast.unparse(keyword.value)}"
        for keyword in node.keywords
        if keyword.arg is not None
    )
    return ClassDeclaration(
        name=node.name,
        qualified_name=(node.name,),
        type_parameters=tuple(
            parse_type_parameter(path, source, parameter, bindings)
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec)
        ),
        bases=bases,
        keywords=keywords,
        decorators=tuple(ast.unparse(item) for item in node.decorator_list),
        fields=fields,
        methods=methods,
        span=source_span(path, node),
    )


def _parse_class_field(
    path: Path,
    source: str,
    node: ast.AnnAssign,
    bindings: ImportBindings,
) -> ClassField:
    annotation = parse_annotation(path, source, node.annotation, bindings)
    target = node.target
    if not isinstance(target, ast.Name):
        raise AssertionError("class fields require named targets")

    return ClassField(
        target.id,
        annotation,
        source_span(path, node),
        node.value is not None,
    )


def _parse_typed_dicts(
    path: Path,
    source: str,
    scoped_statements: tuple[tuple[ast.stmt, tuple[str, ...]], ...],
    bindings: ImportBindings,
) -> tuple[TypedDictDeclaration, ...]:
    declarations: list[TypedDictDeclaration] = []
    known: set[tuple[str, ...]] = set()
    for statement, scope in scoped_statements:
        if isinstance(statement, ast.ClassDef) and _is_typed_dict(
            statement, scope, bindings, known
        ):
            declaration = _parse_typed_dict(
                path, source, statement, scope, bindings, known
            )
            declarations.append(declaration)
            known.add(declaration.qualified_name)

    return tuple(declarations)


def _is_typed_dict(
    node: ast.ClassDef,
    scope: tuple[str, ...],
    bindings: ImportBindings,
    known: set[tuple[str, ...]],
) -> bool:
    typed_dict_bases = {
        ("typing", "TypedDict"),
        ("typing_extensions", "TypedDict"),
    }
    resolved_bases = tuple(
        _resolve_base_name(base, scope, bindings, known) for base in node.bases
    )
    return any(base in typed_dict_bases or base in known for base in resolved_bases)


def _parse_typed_dict(
    path: Path,
    source: str,
    node: ast.ClassDef,
    scope: tuple[str, ...],
    bindings: ImportBindings,
    known: set[tuple[str, ...]],
) -> TypedDictDeclaration:
    total = _typed_dict_total(node)
    fields = tuple(
        _parse_typed_dict_field(path, source, statement, total, bindings)
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
    )
    bases = tuple(
        qualified_name
        for base in node.bases
        if (qualified_name := _resolve_base_name(base, scope, bindings, known))
        is not None
        and qualified_name
        not in {
            None,
            ("typing", "TypedDict"),
            ("typing_extensions", "TypedDict"),
        }
    )
    return TypedDictDeclaration(
        name=node.name,
        qualified_name=(*scope, node.name),
        fields=fields,
        bases=bases,
        total=total,
        span=source_span(path, node),
    )


def _resolve_base_name(
    node: ast.expr,
    scope: tuple[str, ...],
    bindings: ImportBindings,
    known: set[tuple[str, ...]],
) -> tuple[str, ...] | None:
    resolved = resolve_ast_name(node, bindings)
    if resolved is not None:
        return resolved

    if not isinstance(node, ast.Name | ast.Attribute):
        return None

    name = expression_name(node)
    scoped_name = (*scope, *name)
    if scoped_name in known:
        return scoped_name

    if name in known:
        return name

    return None


def _typed_dict_total(node: ast.ClassDef) -> bool:
    for keyword in node.keywords:
        if (
            keyword.arg == "total"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, bool)
        ):
            return keyword.value.value

    return True


def _parse_typed_dict_field(
    path: Path,
    source: str,
    node: ast.AnnAssign,
    total: bool,
    bindings: ImportBindings,
) -> TypedDictField:
    required, readonly, value_node = _typed_dict_field_attributes(
        node.annotation, total, False, bindings
    )
    annotation = parse_annotation(path, source, value_node, bindings)
    target = node.target
    if not isinstance(target, ast.Name):
        raise AssertionError("TypedDict fields require named targets")

    return TypedDictField(
        name=target.id,
        annotation=annotation,
        required=required,
        readonly=readonly,
        span=source_span(path, node),
    )


def _typed_dict_field_attributes(
    node: ast.expr,
    required: bool,
    readonly: bool,
    bindings: ImportBindings,
) -> tuple[bool, bool, ast.expr]:
    annotated_value = unwrap_annotated(node, bindings)
    if annotated_value is not None:
        return _typed_dict_field_attributes(
            annotated_value,
            required,
            readonly,
            bindings,
        )

    if not isinstance(node, ast.Subscript):
        return required, readonly, node

    qualified_name = resolve_ast_name(node.value, bindings)
    arguments = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
    if qualified_name in {
        ("typing", "Required"),
        ("typing_extensions", "Required"),
    }:
        return _typed_dict_field_attributes(arguments[-1], True, readonly, bindings)

    if qualified_name in {
        ("typing", "NotRequired"),
        ("typing_extensions", "NotRequired"),
    }:
        return _typed_dict_field_attributes(arguments[-1], False, readonly, bindings)

    if qualified_name in {
        ("typing", "ReadOnly"),
        ("typing_extensions", "ReadOnly"),
    }:
        return _typed_dict_field_attributes(arguments[-1], required, True, bindings)

    return required, readonly, node


def _parse_parameters(
    path: Path,
    source: str,
    arguments: ast.arguments,
    bindings: ImportBindings,
) -> tuple[Parameter, ...]:
    parameters: list[Parameter] = []
    positional = (*arguments.posonlyargs, *arguments.args)
    default_start = len(positional) - len(arguments.defaults)
    for index, argument in enumerate(arguments.posonlyargs):
        parameters.append(
            _parse_parameter(
                path,
                source,
                argument,
                ParameterKind.POSITIONAL_ONLY,
                index >= default_start,
                bindings,
            )
        )

    for offset, argument in enumerate(arguments.args, start=len(arguments.posonlyargs)):
        parameters.append(
            _parse_parameter(
                path,
                source,
                argument,
                ParameterKind.POSITIONAL_OR_KEYWORD,
                offset >= default_start,
                bindings,
            )
        )

    if arguments.vararg is not None:
        parameters.append(
            _parse_parameter(
                path,
                source,
                arguments.vararg,
                ParameterKind.VAR_POSITIONAL,
                False,
                bindings,
            )
        )

    for argument, default in zip(
        arguments.kwonlyargs, arguments.kw_defaults, strict=True
    ):
        parameters.append(
            _parse_parameter(
                path,
                source,
                argument,
                ParameterKind.KEYWORD_ONLY,
                default is not None,
                bindings,
            )
        )

    if arguments.kwarg is not None:
        parameters.append(
            _parse_parameter(
                path,
                source,
                arguments.kwarg,
                ParameterKind.VAR_KEYWORD,
                False,
                bindings,
            )
        )

    return tuple(parameters)


def _parse_parameter(
    path: Path,
    source: str,
    argument: ast.arg,
    kind: ParameterKind,
    has_default: bool,
    bindings: ImportBindings,
) -> Parameter:
    return Parameter(
        name=argument.arg,
        kind=kind,
        annotation=parse_annotation(path, source, argument.annotation, bindings),
        span=source_span(path, argument),
        has_default=has_default,
    )
