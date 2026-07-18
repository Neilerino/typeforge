from collections.abc import Iterable

from returns.result import Failure, Result, Success

from typeforge.compiler.lowering import (
    ClassDeclaration,
    ClassField,
    Declaration,
    FixedTuple,
    FunctionDeclaration,
    HomogeneousTuple,
    LiteralType,
    Parameter,
    ParameterKind,
    StubModule,
    TypeAliasDeclaration,
    TypeApplication,
    TypeExpression,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
)


def emit_stub_module(module: StubModule) -> Result[str, str]:
    declarations = _collect(_emit_declaration(item) for item in module.declarations)
    return declarations.map(lambda items: _render_stub_module(module, items))


def _render_stub_module(module: StubModule, declarations: tuple[str, ...]) -> str:
    imports = [
        f"from {item.module} import {', '.join(item.names)}"
        for item in sorted(module.imports)
    ]
    sections = [
        section
        for section in ("\n".join(imports), "\n\n".join(declarations))
        if section
    ]
    return "\n\n".join(sections) + "\n"


def emit_type_expression(expression: TypeExpression) -> Result[str, str]:
    return _emit_type(expression)


def _emit_declaration(declaration: Declaration) -> Result[str, str]:
    if isinstance(declaration, FunctionDeclaration):
        return _emit_function(declaration)
    if isinstance(declaration, TypeAliasDeclaration):
        type_parameters = _emit_type_parameters(declaration.type_parameters)
        return _emit_type(declaration.value).map(
            lambda value: f"type {declaration.name}{type_parameters} = {value}"
        )
    if isinstance(declaration, ClassDeclaration):
        return _emit_class(declaration)

    signatures = _collect(
        _emit_function(signature).map(lambda value: f"@overload\n{value}")
        for signature in declaration.signatures
    )
    return Result.do(
        f"{'\n'.join(values)}\n@overload\n{fallback}"
        for values in signatures
        for fallback in _emit_function(declaration.fallback)
    )


def _emit_function(declaration: FunctionDeclaration) -> Result[str, str]:
    type_parameters = _emit_type_parameters(declaration.type_parameters)
    parameters = _emit_parameters(declaration.parameters)
    return_type = _emit_type(declaration.return_type)
    prefix = "async def" if declaration.is_async else "def"
    decorators = "\n".join(f"@{item}" for item in declaration.decorators)
    return Result.do(
        (f"{decorators}\n" if decorators else "")
        + f"{prefix} {declaration.name}{type_parameters}"
        + f"({rendered_parameters}) -> {rendered_return}: ..."
        for rendered_parameters in parameters
        for rendered_return in return_type
    )


def _emit_class(declaration: ClassDeclaration) -> Result[str, str]:
    return Result.do(
        _render_class_body(declaration, _class_header(declaration, bases), members)
        for bases in _emit_types(declaration.bases)
        for members in _collect(
            (
                *(_emit_class_field(field) for field in declaration.fields),
                *(_emit_declaration(method) for method in declaration.methods),
            )
        )
    )


def _class_header(declaration: ClassDeclaration, bases: tuple[str, ...]) -> str:
    header_arguments = (*bases, *declaration.keywords)
    type_parameters = _emit_type_parameters(declaration.type_parameters)
    header = f"class {declaration.name}{type_parameters}"
    return f"{header}({', '.join(header_arguments)})" if header_arguments else header


def _render_class_body(
    declaration: ClassDeclaration, header: str, members: tuple[str, ...]
) -> str:
    body = "\n\n".join(members) or "pass"
    indented = "\n".join(f"    {line}" if line else "" for line in body.splitlines())
    decorators = "\n".join(f"@{item}" for item in declaration.decorators)
    rendered = f"{header}:\n{indented}"
    return f"{decorators}\n{rendered}" if decorators else rendered


def _emit_class_field(field: ClassField) -> Result[str, str]:
    default = f" = {field.default}" if field.default is not None else ""
    return _emit_type(field.annotation).map(
        lambda annotation: f"{field.name}: {annotation}{default}"
    )


def _emit_type_parameters(parameters: tuple[str, ...]) -> str:
    return f"[{', '.join(parameters)}]" if parameters else ""


def _emit_parameters(parameters: tuple[Parameter, ...]) -> Result[str, str]:
    rendered: list[str] = []
    positional_only_end = 0
    keyword_only_started = False
    has_var_positional = False
    for parameter in parameters:
        if (
            parameter.kind is ParameterKind.KEYWORD_ONLY
            and not has_var_positional
            and not keyword_only_started
        ):
            rendered.append("*")
            keyword_only_started = True
        annotation = _emit_type(parameter.annotation)
        if isinstance(annotation, Failure):
            return annotation
        prefix = ""
        if parameter.kind is ParameterKind.VAR_POSITIONAL:
            prefix = "*"
            has_var_positional = True
            keyword_only_started = True
        elif parameter.kind is ParameterKind.VAR_KEYWORD:
            prefix = "**"
        value = f"{prefix}{parameter.name}: {annotation.unwrap()}"
        if parameter.default is not None:
            value = f"{value} = {parameter.default}"
        rendered.append(value)
        if parameter.kind is ParameterKind.POSITIONAL_ONLY:
            positional_only_end = len(rendered)
    if positional_only_end:
        rendered.insert(positional_only_end, "/")
    return Success(", ".join(rendered))


def _emit_type(expression: TypeExpression) -> Result[str, str]:
    if isinstance(expression, (TypeName, TypeVariable)):
        return Success(expression.name)
    if isinstance(expression, TypeApplication):
        return Result.do(
            f"{constructor}[{', '.join(arguments)}]"
            for constructor in _emit_type(expression.constructor)
            for arguments in _emit_types(expression.arguments)
        )
    if isinstance(expression, FixedTuple):
        if not expression.items:
            return Success("tuple[()]")
        return _emit_types(expression.items).map(
            lambda items: f"tuple[{', '.join(items)}]"
        )
    if isinstance(expression, HomogeneousTuple):
        return _emit_type(expression.item).map(lambda item: f"tuple[{item}, ...]")
    if isinstance(expression, LiteralType):
        return Success(f"Literal[{expression.value!r}]")
    if isinstance(expression, UnionExpression):
        return _emit_types(expression.members).map(" | ".join)
    if isinstance(expression, UnpackedType):
        return _emit_type(expression.item).map(lambda item: f"*{item}")
    return Failure(f"unlowered type expression: {type(expression).__name__}")


def _emit_types(
    expressions: tuple[TypeExpression, ...],
) -> Result[tuple[str, ...], str]:
    return _collect(_emit_type(expression) for expression in expressions)


def _collect[ValueType, ErrorType](
    results: Iterable[Result[ValueType, ErrorType]],
) -> Result[tuple[ValueType, ...], ErrorType]:
    values: list[ValueType] = []
    for result in results:
        if isinstance(result, Failure):
            return result
        values.append(result.unwrap())
    return Success(tuple(values))
