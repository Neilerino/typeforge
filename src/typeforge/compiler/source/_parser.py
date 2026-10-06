import ast
from dataclasses import dataclass, replace
from pathlib import Path

from returns.result import Failure, Result, Success

from typeforge.compiler.source._markers import (
    MarkerNormalizationError,
    bind_map_selector,
)
from typeforge.compiler.source._model import (
    AppliedTypeExpression,
    CaptureTypeExpression,
    ClassDeclaration,
    ClassField,
    FieldConstructionTypeExpression,
    FieldReferenceTypeExpression,
    FieldReplacementTypeExpression,
    FunctionDeclaration,
    IdentifierOccurrence,
    MarkerKind,
    MarkerTypeExpression,
    ModuleVariable,
    NameTypeExpression,
    Parameter,
    ParameterKind,
    RawTypeExpression,
    RecordTypeExpression,
    ReturnSite,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceModule,
    SourcePosition,
    SourceSpan,
    SourceTypeExpression,
    StarredTypeExpression,
    TypeAliasDeclaration,
    TypedDictDeclaration,
    TypedDictField,
    TypeParameter,
    TypeParameterKind,
    UnionTypeExpression,
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


@dataclass(frozen=True, slots=True)
class _ImportBindings:
    names: tuple[tuple[str, tuple[str, ...]], ...]
    captures: tuple[tuple[str, CaptureTypeExpression], ...] = ()
    fields: tuple[tuple[str, FieldReferenceTypeExpression], ...] = ()


@dataclass(frozen=True, slots=True)
class _AnnotationSyntaxError(Exception):
    message: str
    span: SourceSpan


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
    except _AnnotationSyntaxError as error:
        return Failure(SourceSyntaxError(path, error.message, error.span))


def _parse_source(source: str, path: Path) -> ParsedSource:
    tree = ast.parse(source, filename=str(path), type_comments=True)
    bindings = _capture_bindings(
        path, tree.body, _collect_import_bindings(tree), strict=False
    )
    scoped_statements = _scoped_statements(tree)
    functions = tuple(
        _parse_function(path, source, node, scope, bindings)
        for node, scope in scoped_statements
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not _is_type_function(node, bindings)
    )
    aliases = tuple(
        _parse_type_alias(path, source, node, scope, bindings)
        for node, scope in scoped_statements
        if isinstance(node, ast.TypeAlias)
    ) + tuple(
        _parse_type_function(path, source, node, scope, bindings)
        for node, scope in scoped_statements
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and _is_type_function(node, bindings)
    )
    typed_dicts = _parse_typed_dicts(path, source, scoped_statements, bindings)
    classes = _parse_classes(path, source, tree, bindings, typed_dicts)
    field_spans = {field.span for record in typed_dicts for field in record.fields}
    field_spans.update(
        field.span for declaration in classes for field in declaration.fields
    )
    variable_annotations: list[SourceTypeExpression] = []
    variables: list[ModuleVariable] = []
    module_variable_nodes = {
        id(node) for node in tree.body if isinstance(node, ast.AnnAssign)
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign) or _span(path, node) in field_spans:
            continue

        annotation = _parse_annotation(path, source, node.annotation, bindings)
        if annotation is not None:
            if (
                id(node) in module_variable_nodes
                and isinstance(node.target, ast.Name)
                and not node.target.id.startswith("_")
            ):
                variables.append(
                    ModuleVariable(node.target.id, annotation, _span(path, node))
                )
            else:
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
        variables=tuple(variables),
        captures=bindings.captures,
        text=source,
        docstring_span=_docstring_span(path, tree),
        future_import_spans=_future_import_spans(path, tree),
        return_sites=tuple(
            ReturnSite(
                statement=_span(path, node),
                expression=_span(path, node.value) if node.value is not None else None,
            )
            for node in located_nodes
            if isinstance(node, ast.Return)
        ),
        identifiers=tuple(
            IdentifierOccurrence(
                name=node.id if isinstance(node, ast.Name) else node.arg,
                span=_span(path, node),
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
            return _span(path, first)

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

        spans.append(_span(path, statement))

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


def _collect_import_bindings(module: ast.Module) -> _ImportBindings:
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

    return _ImportBindings(names=tuple(bindings))


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
    bindings: _ImportBindings,
) -> FunctionDeclaration:
    return FunctionDeclaration(
        name=node.name,
        qualified_name=(*scope, node.name),
        parameters=_parse_parameters(path, source, node.args, bindings),
        returns=_parse_annotation(path, source, node.returns, bindings),
        type_parameters=tuple(
            _parse_type_parameter(path, source, parameter, bindings)
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec)
        ),
        span=_span(path, node),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        decorators=tuple(ast.unparse(item) for item in node.decorator_list),
        decorator_spans=tuple(_span(path, item) for item in node.decorator_list),
        body_span=SourceSpan(
            path=path,
            start=_span(path, node.body[0]).start,
            end=_span(path, node.body[-1]).end,
        ),
    )


def _parse_type_alias(
    path: Path,
    source: str,
    node: ast.TypeAlias,
    scope: tuple[str, ...],
    bindings: _ImportBindings,
) -> TypeAliasDeclaration:
    value = _parse_annotation(path, source, node.value, bindings)
    if value is None:
        value = RawTypeExpression(
            source=ast.unparse(node.value), span=_span(path, node.value)
        )

    return TypeAliasDeclaration(
        name=node.name.id,
        qualified_name=(*scope, node.name.id),
        type_parameters=tuple(
            _parse_type_parameter(path, source, parameter, bindings)
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec)
        ),
        value=value,
        span=_span(path, node),
    )


def _is_type_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef, bindings: _ImportBindings
) -> bool:
    return any(
        isinstance(decorator, ast.Name | ast.Attribute)
        and _resolve_ast_name(decorator, bindings) == ("typeforge", "type_function")
        for decorator in node.decorator_list
    )


def _validate_type_function_signature(
    path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    scope: tuple[str, ...],
) -> None:
    if (
        scope
        or isinstance(node, ast.AsyncFunctionDef)
        or node.args.posonlyargs
        or node.args.args
        or node.args.kwonlyargs
        or node.args.vararg is not None
        or node.args.kwarg is not None
        or len(node.decorator_list) != 1
    ):
        raise _AnnotationSyntaxError(
            "type_function requires a module-level synchronous function without "
            "value parameters or other decorators",
            _span(path, node),
        )

    if any(not isinstance(parameter, ast.TypeVar) for parameter in node.type_params):
        raise _AnnotationSyntaxError(
            "type_function requires ordinary type parameters", _span(path, node)
        )

    if any(
        isinstance(parameter, ast.TypeVar)
        and (parameter.bound is not None or parameter.default_value is not None)
        for parameter in node.type_params
    ):
        raise _AnnotationSyntaxError(
            "type_function currently requires unconstrained parameters "
            "without defaults",
            _span(path, node),
        )


def _type_function_body(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.stmt]:
    body = node.body
    if (
        isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]

    return body


def _type_function_return(
    path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef
) -> ast.expr:
    body = _type_function_body(node)
    if not body or not isinstance(body[-1], ast.Return) or body[-1].value is None:
        raise _AnnotationSyntaxError(
            "type_function currently requires one final return of a type expression",
            _span(path, body[0] if body else node),
        )

    return body[-1].value


def _validate_construction_expression(
    path: Path, node: ast.AST, bindings: _ImportBindings
) -> None:
    if isinstance(node, ast.expr):
        annotated = _annotated_value(node, bindings)
        if annotated is not None:
            _validate_construction_expression(path, annotated, bindings)
            return

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name | ast.Attribute) and _resolve_ast_name(
            node.func, bindings
        ) == ("typeforge", "Field"):
            for keyword in node.keywords:
                _validate_construction_expression(path, keyword.value, bindings)

            return

        if _is_field_replacement(node, bindings):
            assert isinstance(node.func, ast.Attribute)
            _validate_construction_expression(path, node.func.value, bindings)
            for keyword in node.keywords:
                _validate_construction_expression(path, keyword.value, bindings)

            return

        generator = _record_generator(path, node, bindings)
        # The element is validated by _parse_record after its lexical field
        # binding exists; the operand still belongs to the enclosing scope.
        _validate_construction_expression(path, generator.generators[0].iter, bindings)
        return

    if isinstance(
        node,
        ast.Lambda
        | ast.ListComp
        | ast.SetComp
        | ast.DictComp
        | ast.GeneratorExp
        | ast.NamedExpr
        | ast.IfExp
        | ast.BoolOp
        | ast.Compare,
    ) or (isinstance(node, ast.BinOp) and not isinstance(node.op, ast.BitOr)):
        raise _AnnotationSyntaxError(
            "unsupported type_function construction expression", _span(path, node)
        )

    for child in ast.iter_child_nodes(node):
        _validate_construction_expression(path, child, bindings)


def _record_generator(
    path: Path, node: ast.Call, bindings: _ImportBindings
) -> ast.GeneratorExp:
    if not (
        isinstance(node.func, ast.Name | ast.Attribute)
        and _resolve_ast_name(node.func, bindings) == ("typeforge", "Record")
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.GeneratorExp)
    ):
        raise _AnnotationSyntaxError(
            "unsupported type_function construction; Record requires a Fields "
            "generator",
            _span(path, node),
        )

    generator = node.args[0]
    if len(generator.generators) != 1:
        raise _AnnotationSyntaxError(
            "Record currently requires one Fields iteration", _span(path, generator)
        )

    iteration = generator.generators[0]
    if not (
        isinstance(iteration.target, ast.Name)
        and not iteration.ifs
        and not iteration.is_async
        and isinstance(iteration.iter, ast.Subscript)
        and isinstance(iteration.iter.value, ast.Name | ast.Attribute)
        and _resolve_ast_name(iteration.iter.value, bindings) == ("typeforge", "Fields")
        and not isinstance(iteration.iter.slice, ast.Tuple)
    ):
        raise _AnnotationSyntaxError(
            "Record requires one named binding over Fields[T], without filters",
            _span(path, generator),
        )

    return generator


def _capture_bindings(
    path: Path,
    statements: list[ast.stmt],
    bindings: _ImportBindings,
    *,
    strict: bool,
) -> _ImportBindings:
    captures = dict(bindings.captures)
    declared: set[str] = set()
    for statement in statements:
        if strict and isinstance(statement, ast.TypeAlias):
            continue

        declaration = _capture_declaration(path, statement, bindings)
        if declaration is None:
            if strict:
                raise _AnnotationSyntaxError(
                    "type_function supports capture declarations and local aliases "
                    "before its final return",
                    _span(path, statement),
                )

            continue

        variable, expression = declaration
        if variable in declared:
            raise _AnnotationSyntaxError(
                f"capture {variable!r} is declared more than once",
                _span(path, statement),
            )

        declared.add(variable)
        captures[variable] = expression

    return _ImportBindings(
        names=tuple(item for item in bindings.names if item[0] not in declared),
        captures=tuple(captures.items()),
    )


def _capture_declaration(
    path: Path,
    statement: ast.stmt,
    bindings: _ImportBindings,
) -> tuple[str, CaptureTypeExpression] | None:
    if not (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name | ast.Attribute)
        and _resolve_ast_name(statement.value.func, bindings)
        == ("typeforge", "Capture")
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
        raise _AnnotationSyntaxError(
            "Capture requires one nonempty literal string name", _span(path, call)
        )

    variable = statement.targets[0].id
    span = _span(path, statement)
    return variable, CaptureTypeExpression(
        source=variable,
        span=span,
        name=call.args[0].value,
        declaration=span,
    )


def _parse_type_function(
    path: Path,
    source: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    scope: tuple[str, ...],
    bindings: _ImportBindings,
) -> TypeAliasDeclaration:
    _validate_type_function_signature(path, node, scope)
    returned = _type_function_return(path, node)
    parameters = tuple(
        _parse_type_parameter(path, source, parameter, bindings)
        for parameter in node.type_params
        if isinstance(parameter, ast.TypeVar)
    )
    parameter_names = {parameter.name for parameter in parameters}
    local_bindings = _ImportBindings(
        names=(
            *(item for item in bindings.names if item[0] not in parameter_names),
            *(
                (parameter.name, (node.name, parameter.name))
                for parameter in parameters
            ),
        ),
        captures=tuple(
            item for item in bindings.captures if item[0] not in parameter_names
        ),
    )
    local_bindings = _capture_bindings(
        path, _type_function_body(node)[:-1], local_bindings, strict=True
    )
    local_aliases, local_bindings = _parse_local_aliases(
        path, source, node, local_bindings
    )
    _validate_construction_expression(path, returned, local_bindings)
    value = _parse_annotation(path, source, returned, local_bindings)
    assert value is not None
    if isinstance(value, RawTypeExpression) and not (
        isinstance(returned, ast.Constant) and returned.value is None
    ):
        raise _AnnotationSyntaxError(
            "type_function must return a type expression", _span(path, returned)
        )

    return TypeAliasDeclaration(
        name=node.name,
        qualified_name=(node.name,),
        type_parameters=parameters,
        value=value,
        span=_span(path, node),
        is_type_function=True,
        local_aliases=local_aliases,
    )


def _parse_local_aliases(
    path: Path,
    source: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    bindings: _ImportBindings,
) -> tuple[tuple[TypeAliasDeclaration, ...], _ImportBindings]:
    statements = _type_function_body(node)[:-1]
    declarations = [item for item in statements if isinstance(item, ast.TypeAlias)]
    declared = {
        item.targets[0].id
        for item in statements
        if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name)
    }
    for alias in declarations:
        if alias.name.id in declared:
            raise _AnnotationSyntaxError(
                f"type_function local name {alias.name.id!r} "
                "is declared more than once",
                _span(path, alias),
            )

        declared.add(alias.name.id)

    names = {alias.name.id for alias in declarations}
    bindings = replace(
        bindings,
        names=(
            *(item for item in bindings.names if item[0] not in names),
            *((name, (node.name, name)) for name in sorted(names)),
        ),
        captures=tuple(item for item in bindings.captures if item[0] not in names),
    )
    aliases: list[TypeAliasDeclaration] = []
    for alias in declarations:
        if any(
            not isinstance(parameter, ast.TypeVar)
            or parameter.bound is not None
            or parameter.default_value is not None
            for parameter in alias.type_params
        ):
            raise _AnnotationSyntaxError(
                "type_function local aliases require unconstrained ordinary "
                "type parameters without defaults",
                _span(path, alias),
            )

        parameter_names = {
            parameter.name
            for parameter in alias.type_params
            if isinstance(parameter, ast.TypeVar)
        }
        alias_bindings = replace(
            bindings,
            names=(
                *(item for item in bindings.names if item[0] not in parameter_names),
                *(
                    (name, (node.name, alias.name.id, name))
                    for name in sorted(parameter_names)
                ),
            ),
            captures=tuple(
                item for item in bindings.captures if item[0] not in parameter_names
            ),
        )
        _validate_construction_expression(path, alias.value, alias_bindings)
        aliases.append(
            _parse_type_alias(path, source, alias, (node.name,), alias_bindings)
        )

    return tuple(aliases), bindings


def _parse_classes(
    path: Path,
    source: str,
    module: ast.Module,
    bindings: _ImportBindings,
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
    bindings: _ImportBindings,
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
    bases = tuple(
        expression
        for base in node.bases
        if (expression := _parse_annotation(path, source, base, bindings)) is not None
    )
    keywords = tuple(
        f"{keyword.arg}={ast.unparse(keyword.value)}"
        for keyword in node.keywords
        if keyword.arg is not None
    )
    return ClassDeclaration(
        name=node.name,
        qualified_name=(node.name,),
        type_parameters=tuple(
            _parse_type_parameter(path, source, parameter, bindings)
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec)
        ),
        bases=bases,
        keywords=keywords,
        decorators=tuple(ast.unparse(item) for item in node.decorator_list),
        fields=fields,
        methods=methods,
        span=_span(path, node),
    )


def _parse_class_field(
    path: Path,
    source: str,
    node: ast.AnnAssign,
    bindings: _ImportBindings,
) -> ClassField:
    annotation = _parse_annotation(path, source, node.annotation, bindings)
    if annotation is None:
        annotation = RawTypeExpression(
            source=ast.unparse(node.annotation), span=_span(path, node.annotation)
        )

    target = node.target
    if not isinstance(target, ast.Name):
        raise AssertionError("class fields require named targets")

    return ClassField(
        target.id,
        annotation,
        _span(path, node),
        node.value is not None,
    )


def _parse_typed_dicts(
    path: Path,
    source: str,
    scoped_statements: tuple[tuple[ast.stmt, tuple[str, ...]], ...],
    bindings: _ImportBindings,
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
    bindings: _ImportBindings,
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
    bindings: _ImportBindings,
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
        span=_span(path, node),
    )


def _resolve_base_name(
    node: ast.expr,
    scope: tuple[str, ...],
    bindings: _ImportBindings,
    known: set[tuple[str, ...]],
) -> tuple[str, ...] | None:
    resolved = _resolve_ast_name(node, bindings)
    if resolved is not None:
        return resolved

    if not isinstance(node, ast.Name | ast.Attribute):
        return None

    name = _expression_name(node)
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
    bindings: _ImportBindings,
) -> TypedDictField:
    required, readonly, value_node = _typed_dict_field_attributes(
        node.annotation, total, False, bindings
    )
    annotation = _parse_annotation(path, source, value_node, bindings)
    if annotation is None:
        annotation = RawTypeExpression(
            source=ast.unparse(value_node), span=_span(path, value_node)
        )

    target = node.target
    if not isinstance(target, ast.Name):
        raise AssertionError("TypedDict fields require named targets")

    return TypedDictField(
        name=target.id,
        annotation=annotation,
        required=required,
        readonly=readonly,
        span=_span(path, node),
    )


def _typed_dict_field_attributes(
    node: ast.expr,
    required: bool,
    readonly: bool,
    bindings: _ImportBindings,
) -> tuple[bool, bool, ast.expr]:
    annotated_value = _annotated_value(node, bindings)
    if annotated_value is not None:
        return _typed_dict_field_attributes(
            annotated_value,
            required,
            readonly,
            bindings,
        )

    if not isinstance(node, ast.Subscript):
        return required, readonly, node

    qualified_name = _resolve_ast_name(node.value, bindings)
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
    bindings: _ImportBindings,
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
    bindings: _ImportBindings,
) -> Parameter:
    return Parameter(
        name=argument.arg,
        kind=kind,
        annotation=_parse_annotation(path, source, argument.annotation, bindings),
        span=_span(path, argument),
        has_default=has_default,
    )


def _parse_type_parameter(
    path: Path,
    source: str,
    parameter: ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec,
    bindings: _ImportBindings,
) -> TypeParameter:
    if isinstance(parameter, ast.TypeVar):
        kind = TypeParameterKind.TYPE_VAR
    elif isinstance(parameter, ast.TypeVarTuple):
        kind = TypeParameterKind.TYPE_VAR_TUPLE
    else:
        kind = TypeParameterKind.PARAM_SPEC

    domain: SourceTypeExpression | None = None
    if isinstance(parameter, ast.TypeVar) and parameter.bound is not None:
        if isinstance(parameter.bound, ast.Tuple):
            members = tuple(
                expression
                for item in parameter.bound.elts
                if (expression := _parse_annotation(path, source, item, bindings))
                is not None
            )
            domain = UnionTypeExpression(
                source=ast.unparse(parameter.bound),
                span=_span(path, parameter.bound),
                members=members,
            )
        else:
            domain = _parse_annotation(path, source, parameter.bound, bindings)

    return TypeParameter(
        name=parameter.name,
        kind=kind,
        declaration=ast.get_source_segment(source, parameter) or ast.unparse(parameter),
        domain=domain,
        span=_span(path, parameter),
        has_default=parameter.default_value is not None,
    )


def _is_field_replacement(node: ast.Call, bindings: _ImportBindings) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "replace":
        return False

    target = node.func.value
    if isinstance(target, ast.Name):
        return target.id in dict(bindings.fields)

    if isinstance(target, ast.Call):
        return (
            isinstance(target.func, ast.Name | ast.Attribute)
            and _resolve_ast_name(target.func, bindings) == ("typeforge", "Field")
        ) or _is_field_replacement(target, bindings)

    return False


def _field_keywords(
    path: Path, node: ast.Call, *, constructing: bool
) -> dict[str, ast.expr]:
    message = "Field requires keyword data: name, type, required, and readonly"
    if node.args:
        raise _AnnotationSyntaxError(message, _span(path, node))

    keywords: dict[str, ast.expr] = {}
    for keyword in node.keywords:
        if (
            keyword.arg is None
            or keyword.arg not in {"name", "type", "required", "readonly"}
            or keyword.arg in keywords
        ):
            raise _AnnotationSyntaxError(message, _span(path, keyword))

        keywords[keyword.arg] = keyword.value

    if constructing and not {"name", "type"}.issubset(keywords):
        raise _AnnotationSyntaxError(
            "Field requires name and type keywords", _span(path, node)
        )

    return keywords


def _parse_field_replacement(
    path: Path, source: str, node: ast.Call, bindings: _ImportBindings
) -> FieldReplacementTypeExpression:
    assert isinstance(node.func, ast.Attribute)
    keywords = _field_keywords(path, node, constructing=False)
    field = _parse_annotation(path, source, node.func.value, bindings)
    assert field is not None
    return FieldReplacementTypeExpression(
        ast.get_source_segment(source, node) or ast.unparse(node),
        _span(path, node),
        field,
        name=_parse_annotation(path, source, keywords.get("name"), bindings),
        value=_parse_annotation(path, source, keywords.get("type"), bindings),
        required=_field_modifier(path, keywords["required"])
        if "required" in keywords
        else None,
        readonly=_field_modifier(path, keywords["readonly"])
        if "readonly" in keywords
        else None,
    )


def _parse_field(
    path: Path, source: str, node: ast.Call, bindings: _ImportBindings
) -> FieldConstructionTypeExpression:
    keywords = _field_keywords(path, node, constructing=True)
    name = _parse_annotation(path, source, keywords["name"], bindings)
    value = _parse_annotation(path, source, keywords["type"], bindings)
    assert name is not None and value is not None
    return FieldConstructionTypeExpression(
        ast.get_source_segment(source, node) or ast.unparse(node),
        _span(path, node),
        name,
        value,
        required=_field_modifier(path, keywords["required"])
        if "required" in keywords
        else True,
        readonly=_field_modifier(path, keywords["readonly"])
        if "readonly" in keywords
        else False,
    )


def _field_modifier(path: Path, node: ast.expr) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value

    raise _AnnotationSyntaxError("field modifiers must be booleans", _span(path, node))


def _parse_record(
    path: Path, source: str, node: ast.Call, bindings: _ImportBindings
) -> RecordTypeExpression:
    generator = _record_generator(path, node, bindings)
    iteration = generator.generators[0]
    assert isinstance(iteration.target, ast.Name)
    assert isinstance(iteration.iter, ast.Subscript)
    record = _parse_annotation(path, source, iteration.iter.slice, bindings)
    assert record is not None
    name = iteration.target.id
    declaration = _span(path, iteration.target)
    binding = FieldReferenceTypeExpression(name, declaration, name, declaration)
    local = replace(
        bindings,
        fields=(*bindings.fields, (name, binding)),
        names=tuple(item for item in bindings.names if item[0] != name),
        captures=tuple(item for item in bindings.captures if item[0] != name),
    )
    _validate_construction_expression(path, generator.elt, local)
    transform = _parse_annotation(path, source, generator.elt, local)
    assert transform is not None
    return RecordTypeExpression(
        ast.get_source_segment(source, node) or ast.unparse(node),
        _span(path, node),
        record,
        binding,
        transform,
    )


def _parse_annotation(
    path: Path,
    source: str,
    node: ast.expr | None,
    bindings: _ImportBindings,
) -> SourceTypeExpression | None:
    if node is None:
        return None

    rendered = ast.get_source_segment(source, node) or ast.unparse(node)
    span = _span(path, node)
    annotated_value = _annotated_value(node, bindings)
    if annotated_value is not None:
        return _parse_annotation(path, source, annotated_value, bindings)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        members = tuple(
            expression
            for member in _flatten_union_nodes(node)
            if (expression := _parse_annotation(path, source, member, bindings))
            is not None
        )
        return UnionTypeExpression(rendered, span, members)

    if isinstance(node, ast.Starred):
        item = _parse_annotation(path, source, node.value, bindings)
        if item is None:
            return RawTypeExpression(source=rendered, span=span)

        return StarredTypeExpression(rendered, span, item)

    if isinstance(node, ast.Name | ast.Attribute):
        field_name = (
            node.id
            if isinstance(node, ast.Name)
            else (node.value.id if isinstance(node.value, ast.Name) else None)
        )
        field = (
            dict(bindings.fields).get(field_name) if field_name is not None else None
        )
        if field is not None:
            attribute = node.attr if isinstance(node, ast.Attribute) else None
            if attribute not in (None, "name", "type"):
                raise _AnnotationSyntaxError(
                    "unsupported symbolic field attribute", span
                )

            return replace(field, source=rendered, span=span, attribute=attribute)

        if (
            isinstance(node, ast.Name)
            and (capture := dict(bindings.captures).get(node.id)) is not None
        ):
            return replace(capture, source=rendered, span=span)

        name = _expression_name(node)
        name_expression = NameTypeExpression(
            source=rendered,
            span=span,
            name=name,
            qualified_name=_resolve_name(name, bindings),
        )
        if name_expression.qualified_name in {
            ("typeforge", "MapFields"),
            ("typeforge", "Key"),
            ("typeforge", "Value"),
        }:
            raise _AnnotationSyntaxError(
                "field authoring requires Record and Fields", span
            )

        if name_expression.qualified_name in {
            ("typeforge", "OptionalField"),
            ("typeforge", "ReadonlyField"),
        }:
            raise _AnnotationSyntaxError(
                "field authoring requires keyword Field construction", span
            )

        if _is_runtime_input(name_expression):
            return RuntimeInputTypeExpression(rendered, span)

        marker = _marker_kind(name_expression)
        if marker is not None:
            return MarkerTypeExpression(
                source=rendered,
                span=span,
                marker=marker,
                arguments=(),
            )

        return name_expression

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name | ast.Attribute) and _resolve_ast_name(
            node.func, bindings
        ) == ("typeforge", "Field"):
            return _parse_field(path, source, node, bindings)

        if _is_field_replacement(node, bindings):
            return _parse_field_replacement(path, source, node, bindings)

        return _parse_record(path, source, node, bindings)

    if isinstance(node, ast.Subscript):
        if _resolve_ast_name(node.value, bindings) == ("typeforge", "Field"):
            raise _AnnotationSyntaxError("Field requires keyword construction", span)

        constructor = _parse_annotation(path, source, node.value, bindings)
        if constructor is None:
            return RawTypeExpression(source=rendered, span=span)

        slice_nodes = (
            node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
        )
        marker = _marker_kind(constructor)
        public_map = isinstance(node.value, ast.Name | ast.Attribute) and (
            _resolve_name(_expression_name(node.value), bindings)
            == ("typeforge", "Map")
        )
        argument_values: list[SourceTypeExpression] = []
        for slice_node in slice_nodes:
            if public_map:
                if not argument_values and isinstance(slice_node, ast.Slice):
                    raise _AnnotationSyntaxError(
                        "Map requires a subject before its branches",
                        _span(path, slice_node),
                    )

                if (
                    len(argument_values) > 1
                    and _marker_kind(argument_values[-1]) is MarkerKind.DEFAULT
                ):
                    raise _AnnotationSyntaxError(
                        "Map fallback must be last; no branch may follow it",
                        _span(path, slice_node),
                    )

                if argument_values and not isinstance(slice_node, ast.Slice):
                    raise _AnnotationSyntaxError(
                        "Map entries must use selector: output or ...: output syntax",
                        _span(path, slice_node),
                    )

            argument = (
                _parse_map_slice(
                    path,
                    source,
                    slice_node,
                    bindings,
                    argument_values[0],
                )
                if marker is MarkerKind.MAP
                and isinstance(slice_node, ast.Slice)
                and argument_values
                else _parse_annotation(path, source, slice_node, bindings)
            )
            if argument is not None:
                argument_values.append(argument)

        arguments = tuple(argument_values)
        if (
            isinstance(node.value, ast.Name | ast.Attribute)
            and _resolve_name(_expression_name(node.value), bindings)
            == ("typeforge", "Is")
            and len(arguments) != 1
        ):
            raise _AnnotationSyntaxError("Is requires one type argument", span)

        if _is_schema_boundary(constructor):
            return SchemaTypeExpression(
                source=rendered,
                span=span,
                arguments=arguments,
            )

        if marker is not None:
            return MarkerTypeExpression(
                source=rendered,
                span=span,
                marker=marker,
                arguments=arguments,
            )

        return AppliedTypeExpression(
            source=rendered,
            span=span,
            constructor=constructor,
            arguments=arguments,
        )

    return RawTypeExpression(source=rendered, span=span)


def _parse_map_slice(
    path: Path,
    source: str,
    node: ast.Slice,
    bindings: _ImportBindings,
    subject: SourceTypeExpression,
) -> MarkerTypeExpression:
    """Normalize branch spelling without changing matching or output semantics."""
    rendered = ast.get_source_segment(source, node) or ast.unparse(node)
    span = _span(path, node)
    if node.step is not None and not (
        isinstance(node.step, ast.Constant) and node.step.value is None
    ):
        raise _AnnotationSyntaxError(
            "Map branches do not accept a slice step", _span(path, node.step)
        )

    output = _parse_annotation(path, source, node.upper, bindings)
    # A missing token denotes None. Anchor synthesized endpoints to the branch
    # that supplied them, while retaining its exact authored spelling above.
    if output is None:
        output = RawTypeExpression("None", span)

    if isinstance(node.lower, ast.Constant) and node.lower.value is Ellipsis:
        return MarkerTypeExpression(rendered, span, MarkerKind.DEFAULT, (output,))

    selector = _parse_annotation(
        path, source, node.lower, bindings
    ) or RawTypeExpression("None", span)

    try:
        bound_selector = bind_map_selector(selector, subject)
    except MarkerNormalizationError as error:
        raise _AnnotationSyntaxError(
            error.message, error.span or selector.span
        ) from error

    return MarkerTypeExpression(
        rendered,
        span,
        MarkerKind.CASE,
        (bound_selector, output),
    )


def _annotated_value(node: ast.expr, bindings: _ImportBindings) -> ast.expr | None:
    if not isinstance(node, ast.Subscript):
        return None

    if _resolve_ast_name(node.value, bindings) not in {
        ("typing", "Annotated"),
        ("typing_extensions", "Annotated"),
    }:
        return None

    arguments = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
    if len(arguments) < 2:
        return None

    return arguments[0]


def _flatten_union_nodes(node: ast.expr) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return (*_flatten_union_nodes(node.left), *_flatten_union_nodes(node.right))

    return (node,)


def _expression_name(node: ast.Name | ast.Attribute) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)

    if isinstance(node.value, ast.Name | ast.Attribute):
        return (*_expression_name(node.value), node.attr)

    return (node.attr,)


def _resolve_name(
    name: tuple[str, ...], bindings: _ImportBindings
) -> tuple[str, ...] | None:
    if not name:
        return None

    imported = dict(bindings.names).get(name[0])
    if imported is None:
        return None

    return (*imported, *name[1:])


def _resolve_ast_name(
    node: ast.expr, bindings: _ImportBindings
) -> tuple[str, ...] | None:
    if not isinstance(node, ast.Name | ast.Attribute):
        return None

    return _resolve_name(_expression_name(node), bindings)


def _marker_kind(expression: SourceTypeExpression) -> MarkerKind | None:
    if isinstance(expression, MarkerTypeExpression):
        return expression.marker

    if not isinstance(expression, NameTypeExpression):
        return None

    qualified_name = expression.qualified_name
    marker_names = {marker.value: marker for marker in MarkerKind}
    if qualified_name is None or len(qualified_name) < 2:
        return None

    if qualified_name[:-1] not in {
        ("typeforge",),
        ("typeforge", "_markers"),
    }:
        return None

    if qualified_name[:-1] == ("typeforge",) and qualified_name[-1] in {
        "Case",
        "Default",
    }:
        return None

    if qualified_name == ("typeforge", "Is"):
        return MarkerKind.EQUAL

    if qualified_name[:-1] == ("typeforge",) and qualified_name[-1] in {
        "Equal",
        "Assignable",
        "All",
        "Any",
        "Not",
    }:
        raise _AnnotationSyntaxError(
            f"{qualified_name[-1]} is no longer a public selector; "
            "use a bare type or Is[Type]",
            expression.span,
        )

    return marker_names.get(qualified_name[-1])


def _is_schema_boundary(expression: SourceTypeExpression) -> bool:
    return isinstance(expression, NameTypeExpression) and expression.qualified_name == (
        "typeforge",
        "pydantic",
        "Schema",
    )


def _is_runtime_input(expression: SourceTypeExpression) -> bool:
    return isinstance(expression, NameTypeExpression) and expression.qualified_name == (
        "typeforge",
        "pydantic",
        "Input",
    )


def _span(
    path: Path,
    node: ast.stmt
    | ast.expr
    | ast.arg
    | ast.keyword
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
