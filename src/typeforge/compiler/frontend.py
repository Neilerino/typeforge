import ast
from dataclasses import dataclass
from pathlib import Path

from returns.result import Failure, Result, Success

from typeforge.compiler.model import (
    AppliedTypeExpression,
    ClassDeclaration,
    ClassField,
    FunctionDeclaration,
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    Parameter,
    ParameterKind,
    RawTypeExpression,
    SourceModule,
    SourcePosition,
    SourceSpan,
    StarredTypeExpression,
    TypeAliasDeclaration,
    TypedDictDeclaration,
    TypedDictField,
    TypeExpression,
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


type FrontendError = SourceReadError | SourceSyntaxError


@dataclass(frozen=True, slots=True)
class _ImportBindings:
    names: tuple[tuple[str, tuple[str, ...]], ...]


def parse_module(path: Path) -> Result[SourceModule, FrontendError]:
    source = _read_source(path)
    if isinstance(source, Failure):
        return source
    return parse_source(source.unwrap(), path)


def parse_source(
    source: str, path: Path = Path("<memory>")
) -> Result[SourceModule, SourceSyntaxError]:
    try:
        tree = ast.parse(source, filename=str(path), type_comments=True)
    except SyntaxError as error:
        return Failure(_syntax_error(path, error))
    bindings = _collect_import_bindings(tree)
    scoped_statements = _scoped_statements(tree)
    functions = tuple(
        _parse_function(path, source, node, scope, bindings)
        for node, scope in scoped_statements
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )
    aliases = tuple(
        _parse_type_alias(path, source, node, scope, bindings)
        for node, scope in scoped_statements
        if isinstance(node, ast.TypeAlias)
    )
    typed_dicts = _parse_typed_dicts(path, source, scoped_statements, bindings)
    classes = _parse_classes(path, source, tree, bindings, typed_dicts)
    return Success(
        SourceModule(
            path=path,
            functions=functions,
            aliases=aliases,
            typed_dicts=typed_dicts,
            classes=classes,
        )
    )


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
            _parse_type_parameter(path, source, parameter)
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec)
        ),
        span=_span(path, node),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        decorators=tuple(ast.unparse(item) for item in node.decorator_list),
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
            _parse_type_parameter(path, source, parameter)
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec)
        ),
        value=value,
        span=_span(path, node),
    )


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
            _parse_type_parameter(path, source, parameter)
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
    if qualified_name in {
        ("typeforge", "Field"),
        ("typeforge", "_markers", "Field"),
    }:
        return required, readonly, arguments[-1]
    if qualified_name in {
        ("typeforge", "OptionalField"),
        ("typeforge", "_markers", "OptionalField"),
    }:
        return False, readonly, arguments[-1]
    if qualified_name in {
        ("typeforge", "ReadonlyField"),
        ("typeforge", "_markers", "ReadonlyField"),
    }:
        return required, True, arguments[-1]
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
) -> TypeParameter:
    if isinstance(parameter, ast.TypeVar):
        kind = TypeParameterKind.TYPE_VAR
    elif isinstance(parameter, ast.TypeVarTuple):
        kind = TypeParameterKind.TYPE_VAR_TUPLE
    else:
        kind = TypeParameterKind.PARAM_SPEC
    return TypeParameter(
        name=parameter.name,
        kind=kind,
        span=_span(path, parameter),
        declaration=ast.get_source_segment(source, parameter) or ast.unparse(parameter),
    )


def _parse_annotation(
    path: Path,
    source: str,
    node: ast.expr | None,
    bindings: _ImportBindings,
) -> TypeExpression | None:
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
        name = _expression_name(node)
        name_expression = NameTypeExpression(
            source=rendered,
            span=span,
            name=name,
            qualified_name=_resolve_name(name, bindings),
        )
        marker = _marker_kind(name_expression)
        if marker is not None:
            return MarkerTypeExpression(
                source=rendered,
                span=span,
                marker=marker,
                arguments=(),
            )
        return name_expression
    if isinstance(node, ast.Subscript):
        constructor = _parse_annotation(path, source, node.value, bindings)
        if constructor is None:
            return RawTypeExpression(source=rendered, span=span)
        slice_nodes = (
            node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
        )
        argument_values: list[TypeExpression] = []
        for slice_node in slice_nodes:
            argument = _parse_annotation(path, source, slice_node, bindings)
            if argument is not None:
                argument_values.append(argument)
        arguments = tuple(argument_values)
        marker = _marker_kind(constructor)
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


def _marker_kind(expression: TypeExpression) -> MarkerKind | None:
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
    return marker_names.get(qualified_name[-1])


def _span(
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
