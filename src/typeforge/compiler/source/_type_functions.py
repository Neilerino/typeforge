import ast
from pathlib import Path

from typeforge.compiler.source._annotations import (
    parse_annotation,
    parse_type_parameter,
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

    returned = body[-1].value
    for item in ast.walk(returned):
        if isinstance(
            item,
            ast.Call
            | ast.Lambda
            | ast.ListComp
            | ast.SetComp
            | ast.DictComp
            | ast.GeneratorExp
            | ast.NamedExpr
            | ast.IfExp
            | ast.BoolOp
            | ast.Compare,
        ) or (isinstance(item, ast.BinOp) and not isinstance(item.op, ast.BitOr)):
            raise AnnotationSyntaxError(
                "unsupported type_function construction expression",
                source_span(path, item),
            )

    return returned


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
    parameter_names = {parameter.name for parameter in parameters}
    local_bindings = ImportBindings(
        names=tuple(item for item in bindings.names if item[0] not in parameter_names),
        captures=tuple(
            item for item in bindings.captures if item[0] not in parameter_names
        ),
    )
    local_bindings = capture_bindings(
        path, _type_function_body(node)[:-1], local_bindings, strict=True
    )
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
    )
