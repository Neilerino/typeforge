from typeforge._result import Err, Ok, Result
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
    declarations: list[str] = []
    for declaration in module.declarations:
        emitted = _emit_declaration(declaration)
        if isinstance(emitted, Err):
            return emitted
        declarations.append(emitted.value)

    imports = [
        f"from {item.module} import {', '.join(item.names)}"
        for item in sorted(module.imports)
    ]
    sections = [
        section
        for section in ("\n".join(imports), "\n\n".join(declarations))
        if section
    ]
    return Ok("\n\n".join(sections) + "\n")


def emit_type_expression(expression: TypeExpression) -> Result[str, str]:
    return _emit_type(expression)


def _emit_declaration(declaration: Declaration) -> Result[str, str]:
    if isinstance(declaration, FunctionDeclaration):
        return _emit_function(declaration)
    if isinstance(declaration, TypeAliasDeclaration):
        type_parameters = _emit_type_parameters(declaration.type_parameters)
        value = _emit_type(declaration.value)
        if isinstance(value, Err):
            return value
        return Ok(f"type {declaration.name}{type_parameters} = {value.value}")
    if isinstance(declaration, ClassDeclaration):
        return _emit_class(declaration)

    signatures: list[str] = []
    for signature in declaration.signatures:
        emitted = _emit_function(signature)
        if isinstance(emitted, Err):
            return emitted
        signatures.append(f"@overload\n{emitted.value}")
    fallback = _emit_function(declaration.fallback)
    if isinstance(fallback, Err):
        return fallback
    return Ok(f"{'\n'.join(signatures)}\n@overload\n{fallback.value}")


def _emit_function(declaration: FunctionDeclaration) -> Result[str, str]:
    type_parameters = _emit_type_parameters(declaration.type_parameters)
    parameters = _emit_parameters(declaration.parameters)
    if isinstance(parameters, Err):
        return parameters
    return_type = _emit_type(declaration.return_type)
    if isinstance(return_type, Err):
        return return_type
    prefix = "async def" if declaration.is_async else "def"
    signature = (
        f"{prefix} {declaration.name}{type_parameters}"
        f"({parameters.value}) -> {return_type.value}: ..."
    )
    decorators = "\n".join(f"@{item}" for item in declaration.decorators)
    return Ok(f"{decorators}\n{signature}" if decorators else signature)


def _emit_class(declaration: ClassDeclaration) -> Result[str, str]:
    bases = _emit_types(declaration.bases)
    if isinstance(bases, Err):
        return bases
    header_arguments = (*bases.value, *declaration.keywords)
    type_parameters = _emit_type_parameters(declaration.type_parameters)
    header = f"class {declaration.name}{type_parameters}"
    if header_arguments:
        header = f"{header}({', '.join(header_arguments)})"
    members: list[str] = []
    for field in declaration.fields:
        emitted = _emit_class_field(field)
        if isinstance(emitted, Err):
            return emitted
        members.append(emitted.value)
    for method in declaration.methods:
        emitted = _emit_declaration(method)
        if isinstance(emitted, Err):
            return emitted
        members.append(emitted.value)
    body = "\n\n".join(members) or "pass"
    indented = "\n".join(f"    {line}" if line else "" for line in body.splitlines())
    decorators = "\n".join(f"@{item}" for item in declaration.decorators)
    rendered = f"{header}:\n{indented}"
    return Ok(f"{decorators}\n{rendered}" if decorators else rendered)


def _emit_class_field(field: ClassField) -> Result[str, str]:
    annotation = _emit_type(field.annotation)
    if isinstance(annotation, Err):
        return annotation
    default = f" = {field.default}" if field.default is not None else ""
    return Ok(f"{field.name}: {annotation.value}{default}")


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
        if isinstance(annotation, Err):
            return annotation
        prefix = ""
        if parameter.kind is ParameterKind.VAR_POSITIONAL:
            prefix = "*"
            has_var_positional = True
            keyword_only_started = True
        elif parameter.kind is ParameterKind.VAR_KEYWORD:
            prefix = "**"
        value = f"{prefix}{parameter.name}: {annotation.value}"
        if parameter.default is not None:
            value = f"{value} = {parameter.default}"
        rendered.append(value)
        if parameter.kind is ParameterKind.POSITIONAL_ONLY:
            positional_only_end = len(rendered)
    if positional_only_end:
        rendered.insert(positional_only_end, "/")
    return Ok(", ".join(rendered))


def _emit_type(expression: TypeExpression) -> Result[str, str]:
    if isinstance(expression, (TypeName, TypeVariable)):
        return Ok(expression.name)
    if isinstance(expression, TypeApplication):
        constructor = _emit_type(expression.constructor)
        if isinstance(constructor, Err):
            return constructor
        arguments = _emit_types(expression.arguments)
        if isinstance(arguments, Err):
            return arguments
        return Ok(f"{constructor.value}[{', '.join(arguments.value)}]")
    if isinstance(expression, FixedTuple):
        if not expression.items:
            return Ok("tuple[()]")
        items = _emit_types(expression.items)
        if isinstance(items, Err):
            return items
        return Ok(f"tuple[{', '.join(items.value)}]")
    if isinstance(expression, HomogeneousTuple):
        item = _emit_type(expression.item)
        return item if isinstance(item, Err) else Ok(f"tuple[{item.value}, ...]")
    if isinstance(expression, LiteralType):
        return Ok(f"Literal[{expression.value!r}]")
    if isinstance(expression, UnionExpression):
        members = _emit_types(expression.members)
        if isinstance(members, Err):
            return members
        return Ok(" | ".join(members.value))
    if isinstance(expression, UnpackedType):
        item = _emit_type(expression.item)
        return item if isinstance(item, Err) else Ok(f"*{item.value}")
    return Err(f"unlowered type expression: {type(expression).__name__}")


def _emit_types(
    expressions: tuple[TypeExpression, ...],
) -> Result[tuple[str, ...], str]:
    values: list[str] = []
    for expression in expressions:
        emitted = _emit_type(expression)
        if isinstance(emitted, Err):
            return emitted
        values.append(emitted.value)
    return Ok(tuple(values))
