import ast
from dataclasses import replace
from pathlib import Path

from typeforge.compiler.source._annotations import (
    parse_annotation,
    parse_type_alias,
    parse_type_parameter,
    validate_construction_expression,
)
from typeforge.compiler.source._model import RawTypeExpression, TypeAliasDeclaration
from typeforge.compiler.source._syntax import (
    AnnotationSyntaxError,
    ImportBindings,
    capture_bindings,
    resolve_ast_name,
    source_span,
)


def is_type_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef, bindings: ImportBindings
) -> bool:
    return any(
        isinstance(decorator, ast.Name | ast.Attribute)
        and resolve_ast_name(decorator, bindings) == ("typeforge", "type_function")
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
        raise AnnotationSyntaxError(
            "type_function requires a module-level synchronous function without "
            "value parameters or other decorators",
            source_span(path, node),
        )

    if any(not isinstance(parameter, ast.TypeVar) for parameter in node.type_params):
        raise AnnotationSyntaxError(
            "type_function requires ordinary type parameters", source_span(path, node)
        )

    if any(
        isinstance(parameter, ast.TypeVar)
        and (parameter.bound is not None or parameter.default_value is not None)
        for parameter in node.type_params
    ):
        raise AnnotationSyntaxError(
            "type_function currently requires unconstrained parameters "
            "without defaults",
            source_span(path, node),
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
        raise AnnotationSyntaxError(
            "type_function currently requires one final return of a type expression",
            source_span(path, body[0] if body else node),
        )

    return body[-1].value


def parse_type_function(
    path: Path,
    source: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    scope: tuple[str, ...],
    bindings: ImportBindings,
) -> TypeAliasDeclaration:
    _validate_type_function_signature(path, node, scope)
    returned = _type_function_return(path, node)
    parameters = tuple(
        parse_type_parameter(source, parameter)
        for parameter in node.type_params
        if isinstance(parameter, ast.TypeVar)
    )
    local_bindings = _bind_names(
        bindings, tuple(parameter.name for parameter in parameters), (node.name,)
    )
    local_bindings = capture_bindings(
        path, _type_function_body(node)[:-1], local_bindings, strict=True
    )
    local_aliases, local_bindings = _parse_local_aliases(
        path, source, node, local_bindings
    )
    validate_construction_expression(path, returned, local_bindings)
    value = parse_annotation(path, source, returned, local_bindings)
    if isinstance(value, RawTypeExpression) and not (
        isinstance(returned, ast.Constant) and returned.value is None
    ):
        raise AnnotationSyntaxError(
            "type_function must return a type expression", source_span(path, returned)
        )

    return TypeAliasDeclaration(
        name=node.name,
        qualified_name=(node.name,),
        type_parameters=parameters,
        value=value,
        span=source_span(path, node),
        is_type_function=True,
        local_aliases=local_aliases,
    )


def _parse_local_aliases(
    path: Path,
    source: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    bindings: ImportBindings,
) -> tuple[tuple[TypeAliasDeclaration, ...], ImportBindings]:
    statements = _type_function_body(node)[:-1]
    declarations = [item for item in statements if isinstance(item, ast.TypeAlias)]
    declared = {
        item.targets[0].id
        for item in statements
        if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name)
    }
    for alias in declarations:
        if alias.name.id in declared:
            raise AnnotationSyntaxError(
                f"type_function local name {alias.name.id!r} "
                "is declared more than once",
                source_span(path, alias),
            )

        declared.add(alias.name.id)

    names = {alias.name.id for alias in declarations}
    bindings = _bind_names(bindings, tuple(sorted(names)), (node.name,))
    aliases: list[TypeAliasDeclaration] = []
    for alias in declarations:
        if any(
            not isinstance(parameter, ast.TypeVar)
            or parameter.bound is not None
            or parameter.default_value is not None
            for parameter in alias.type_params
        ):
            raise AnnotationSyntaxError(
                "type_function local aliases require unconstrained ordinary "
                "type parameters without defaults",
                source_span(path, alias),
            )

        parameter_names = {
            parameter.name
            for parameter in alias.type_params
            if isinstance(parameter, ast.TypeVar)
        }
        alias_bindings = _bind_names(
            bindings, tuple(sorted(parameter_names)), (node.name, alias.name.id)
        )
        validate_construction_expression(path, alias.value, alias_bindings)
        aliases.append(
            parse_type_alias(path, source, alias, (node.name,), alias_bindings)
        )

    return tuple(aliases), bindings


def _bind_names(
    bindings: ImportBindings,
    names: tuple[str, ...],
    scope: tuple[str, ...],
) -> ImportBindings:
    return replace(
        bindings,
        names=(
            *(item for item in bindings.names if item[0] not in names),
            *((name, (*scope, name)) for name in names),
        ),
        captures=tuple(item for item in bindings.captures if item[0] not in names),
    )
