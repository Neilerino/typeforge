"""AST inspection, import handling, and stub-rendering pipeline utilities."""

import ast
from pathlib import Path
from typing import assert_never

from returns.result import Failure, Result, Success

from typeforge.compiler._pipeline_models import (
    ModuleVariables,
    UnsupportedPublicDeclaration,
)
from typeforge.compiler.lowering import Import, ImportFrom, ModuleImport
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceModule,
    StarredTypeExpression,
    UnionTypeExpression,
)
from typeforge.compiler.model import (
    TypeExpression as SourceTypeExpression,
)
from typeforge.compiler.records import (
    NamedType,
    NeverType,
    StaticType,
    TypedDictField,
    TypedDictShape,
    UnionType,
)

_TYPING_ALIAS = "tf_typing"


def render_typed_dict(shape: TypedDictShape) -> str:
    fields = tuple(_render_typed_dict_field(field) for field in shape.fields)
    body = "\n".join(f"    {field}" for field in fields) or "    pass"
    return f"class {shape.name}({_TYPING_ALIAS}.TypedDict):\n{body}"


def _render_typed_dict_field(field: TypedDictField) -> str:
    value = render_static_type(field.value)
    if field.readonly:
        value = f"{_TYPING_ALIAS}.ReadOnly[{value}]"
    if not field.required:
        value = f"{_TYPING_ALIAS}.NotRequired[{value}]"
    return f"{field.name}: {value}"


def render_static_type(value: StaticType) -> str:
    match value:
        case NamedType(name):
            return name
        case NeverType():
            return f"{_TYPING_ALIAS}.Never"
        case UnionType(members):
            return " | ".join(render_static_type(member) for member in members)
        case TypedDictShape(name):
            return name or "object"
        case _ as unreachable:
            assert_never(unreachable)


def merge_imports(imports: tuple[ModuleImport, ...]) -> tuple[ModuleImport, ...]:
    module_imports = tuple(
        dict.fromkeys(item for item in imports if isinstance(item, Import))
    )
    merged: dict[str, set[str]] = {}
    for item in imports:
        if isinstance(item, Import):
            continue
        merged.setdefault(item.module, set()).update(item.names)
    return (
        *module_imports,
        *(ImportFrom(module, tuple(sorted(names))) for module, names in merged.items()),
    )


def inject_declarations(content: str, declarations: tuple[str, ...]) -> str:
    if not declarations:
        return content
    if not content.strip():
        return f"{'\n\n'.join(declarations)}\n"
    rendered = "\n\n".join(declarations)
    lines = content.rstrip().splitlines()
    import_count = 0
    for line in lines:
        if not line.startswith(("from ", "import ")):
            break
        import_count += 1
    if import_count == 0:
        return f"{rendered}\n\n{content.lstrip()}"
    imports = "\n".join(lines[:import_count])
    tail = "\n".join(lines[import_count:]).lstrip()
    if not tail:
        return f"{imports}\n\n{rendered}\n"
    return f"{imports}\n\n{rendered}\n\n{tail}\n"


def annotation_contains_default_never(
    expression: SourceTypeExpression | None,
) -> bool:
    match expression:
        case None:
            return False
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return annotation_contains_default_never(constructor) or any(
                annotation_contains_default_never(argument) for argument in arguments
            )
        case (
            SchemaTypeExpression(arguments=arguments)
            | MarkerTypeExpression(arguments=arguments)
        ):
            if (
                isinstance(expression, MarkerTypeExpression)
                and expression.marker is MarkerKind.MAP
                and not any(
                    isinstance(argument, MarkerTypeExpression)
                    and argument.marker is MarkerKind.DEFAULT
                    for argument in arguments[1:]
                )
            ):
                return True
            return any(
                annotation_contains_default_never(argument) for argument in arguments
            )
        case UnionTypeExpression(members=members):
            return any(annotation_contains_default_never(member) for member in members)
        case StarredTypeExpression(item=item):
            return annotation_contains_default_never(item)
        case NameTypeExpression() | RawTypeExpression() | RuntimeInputTypeExpression():
            return False
        case _ as unreachable:
            assert_never(unreachable)


def validate_public_surface(
    module: SourceModule,
) -> Result[None, UnsupportedPublicDeclaration]:
    source = module.path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module.path), type_comments=True)
    typed_dict_names = {declaration.name for declaration in module.typed_dicts}
    for statement in tree.body:
        unsupported = _unsupported_public_statement(statement, typed_dict_names)
        if unsupported is not None:
            return Failure(
                UnsupportedPublicDeclaration(
                    module.path,
                    statement.lineno,
                    unsupported,
                )
            )
    return Success(None)


def _unsupported_public_statement(
    statement: ast.stmt,
    typed_dict_names: set[str],
) -> str | None:
    match statement:
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ImportFrom() | ast.Pass():
            return None
        case ast.Import(names=aliases):
            if all(alias.name == "typeforge" for alias in aliases):
                return None
            return "plain imports are not yet supported; use a from import"
        case ast.Expr(value=value):
            public_bindings = tuple(
                node.target.id
                for node in ast.walk(value)
                if isinstance(node, ast.NamedExpr)
                and not node.target.id.startswith("_")
            )
            if public_bindings:
                return (
                    "assignment expressions that create public names are not supported"
                )
            return None
        case ast.ClassDef(name=name):
            if name in typed_dict_names or name.startswith("_"):
                return None
            return _unsupported_class_body(statement)
        case ast.TypeAlias() | ast.AnnAssign():
            return None
        case ast.Assign(targets=targets, value=value):
            names = tuple(
                target.id for target in targets if isinstance(target, ast.Name)
            )
            if names == ("__all__",):
                if _static_export_names(value) is not None:
                    return None
                return "__all__ must be a literal list or tuple of names"
            return None
        case ast.If(orelse=otherwise) if _is_runtime_main_guard(statement):
            if otherwise:
                return "runtime main guards with an else branch are not supported"
            return None
        case _:
            return (
                f"public {type(statement).__name__} declarations are not yet supported"
            )


def _unsupported_class_body(declaration: ast.ClassDef) -> str | None:
    for statement in declaration.body:
        if isinstance(
            statement,
            ast.FunctionDef | ast.AsyncFunctionDef | ast.AnnAssign | ast.Pass,
        ):
            continue
        if isinstance(statement, ast.Expr) and isinstance(
            statement.value, ast.Constant
        ):
            continue
        if isinstance(statement, ast.Assign):
            names = tuple(
                target.id
                for target in statement.targets
                if isinstance(target, ast.Name)
            )
            if names and all(name.startswith("_") for name in names):
                continue
        return (
            f"class {declaration.name} contains unsupported "
            f"{type(statement).__name__} declarations"
        )
    return None


def _is_runtime_main_guard(statement: ast.If) -> bool:
    test = statement.test
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False
    left = test.left
    right = test.comparators[0]
    return (_is_dunder_name(left) and _is_main_literal(right)) or (
        _is_main_literal(left) and _is_dunder_name(right)
    )


def _is_dunder_name(expression: ast.expr) -> bool:
    return isinstance(expression, ast.Name) and expression.id == "__name__"


def _is_main_literal(expression: ast.expr) -> bool:
    return isinstance(expression, ast.Constant) and expression.value == "__main__"


def collect_module_variables(path: Path) -> ModuleVariables:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(path), type_comments=True)
    declarations: list[str] = []
    requires_any = False
    for statement in module.body:
        if isinstance(statement, ast.AnnAssign):
            if not isinstance(statement.target, ast.Name):
                continue
            name = statement.target.id
            if name.startswith("_"):
                continue
            annotation = ast.unparse(statement.annotation)
            declarations.append(f"{name}: {annotation}")
            continue
        if not isinstance(statement, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        ):
            continue
        if (
            statement.type_comment is not None
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            name = statement.targets[0].id
            if not name.startswith("_"):
                declarations.append(f"{name}: {statement.type_comment}")
                requires_any = requires_any or _annotation_contains_any(
                    statement.type_comment
                )
            continue
        for target in statement.targets:
            bindings = _infer_assignment_bindings(target, statement.value)
            for name, annotation in bindings:
                if name.startswith("_"):
                    continue
                declarations.append(f"{name}: {annotation}")
                requires_any = requires_any or _annotation_contains_any(annotation)
    return ModuleVariables(tuple(declarations), requires_any)


def _infer_assignment_bindings(
    target: ast.expr, value: ast.expr
) -> tuple[tuple[str, str], ...]:
    match target:
        case ast.Name(id=name):
            return ((name, _infer_value_type(value)),)
        case ast.Starred(value=item):
            return tuple(
                (name, "Any") for name in _collect_assignment_target_names(item)
            )
        case ast.Tuple(elts=targets) | ast.List(elts=targets):
            match value:
                case ast.Tuple(elts=values) | ast.List(elts=values):
                    pass
                case _:
                    values = []
            if len(values) != len(targets):
                return tuple(
                    (name, "Any") for name in _collect_assignment_target_names(target)
                )
            return tuple(
                binding
                for item, item_value in zip(targets, values, strict=True)
                for binding in _infer_assignment_bindings(item, item_value)
            )
        case _:
            return ()


def _collect_assignment_target_names(target: ast.expr) -> tuple[str, ...]:
    match target:
        case ast.Name(id=name):
            return (name,)
        case ast.Starred(value=item):
            return _collect_assignment_target_names(item)
        case ast.Tuple(elts=items) | ast.List(elts=items):
            return tuple(
                name
                for item in items
                for name in _collect_assignment_target_names(item)
            )
        case _:
            return ()


def _infer_value_type(value: ast.expr) -> str:
    match value:
        case ast.Constant(value=constant):
            return _infer_constant_type(constant)
        case ast.Tuple(elts=[]):
            return "tuple[()]"
        case ast.Tuple(elts=items):
            return f"tuple[{', '.join(_infer_value_type(item) for item in items)}]"
        case ast.List(elts=items):
            return f"list[{_infer_collection_item_type(items)}]"
        case ast.Set(elts=items):
            return f"set[{_infer_collection_item_type(items)}]"
        case ast.Dict(keys=raw_keys, values=values):
            keys = tuple(key for key in raw_keys if key is not None)
            if len(keys) != len(raw_keys):
                return "dict[Any, Any]"
            key_type = _infer_collection_item_type(keys)
            value_type = _infer_collection_item_type(values)
            return f"dict[{key_type}, {value_type}]"
        case ast.IfExp(body=when_true, orelse=when_false):
            return _union_annotations(
                (_infer_value_type(when_true), _infer_value_type(when_false))
            )
        case ast.UnaryOp(operand=operand):
            operand_type = _infer_value_type(operand)
            if operand_type in {"int", "float", "complex"}:
                return operand_type
            return "Any"
        case ast.BinOp(left=left_expression, right=right_expression):
            left = _infer_value_type(left_expression)
            right = _infer_value_type(right_expression)
            if left == right and left in {
                "int",
                "float",
                "complex",
                "str",
                "bytes",
            }:
                return left
            return "Any"
        case ast.Call(func=constructor_expression):
            return _infer_constructor_type(constructor_expression) or "Any"
        case ast.Name(id=name) if name[:1].isupper():
            return f"type[{name}]"
        case _:
            return "Any"


def _infer_constant_type(value: object) -> str:
    if value is None:
        return "None"
    if value is Ellipsis:
        return "Any"
    return type(value).__name__


def _infer_collection_item_type(
    values: tuple[ast.expr, ...] | list[ast.expr],
) -> str:
    if not values:
        return "Any"
    return _union_annotations(tuple(_infer_value_type(value) for value in values))


def _union_annotations(annotations: tuple[str, ...]) -> str:
    return " | ".join(dict.fromkeys(annotations))


def _infer_constructor_type(function: ast.expr) -> str | None:
    name = _constructor_name(function)
    if name is None:
        return None
    terminal = name.rsplit(".", 1)[-1].split("[", 1)[0]
    if terminal[:1].isupper() or terminal in {
        "bytes",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "set",
        "str",
        "tuple",
    }:
        return name
    return None


def _constructor_name(function: ast.expr) -> str | None:
    match function:
        case ast.Name() | ast.Attribute() | ast.Subscript():
            return ast.unparse(function)
        case _:
            return None


def _annotation_contains_any(annotation: str) -> bool:
    try:
        parsed = ast.parse(annotation, mode="eval")
    except SyntaxError:
        return annotation == "Any"
    return any(
        isinstance(node, ast.Name) and node.id == "Any" for node in ast.walk(parsed)
    )


def collect_imports(path: Path) -> tuple[ImportFrom, ...]:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(path), type_comments=True)
    exported_names = _collect_export_names(module)
    imports: list[ImportFrom] = []
    for statement in module.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        if (
            statement.level == 0
            and statement.module is not None
            and (
                statement.module == "typeforge"
                or statement.module.startswith("typeforge.")
            )
        ):
            continue
        names = tuple(
            _render_import_name(alias, exported_names) for alias in statement.names
        )
        module_name = f"{'.' * statement.level}{statement.module or ''}"
        imports.append(ImportFrom(module_name, names))
    return tuple(imports)


def _collect_export_names(module: ast.Module) -> frozenset[str]:
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        ):
            continue
        names = _static_export_names(statement.value)
        return frozenset(names or ())
    return frozenset()


def _static_export_names(expression: ast.expr) -> tuple[str, ...] | None:
    if not isinstance(expression, ast.List | ast.Tuple):
        return None
    names = tuple(
        item.value
        for item in expression.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    )
    if len(names) != len(expression.elts):
        return None
    return names


def _render_import_name(alias: ast.alias, exported_names: frozenset[str]) -> str:
    local_name = alias.asname or alias.name
    if alias.asname is not None or local_name in exported_names:
        return f"{alias.name} as {local_name}"
    return alias.name
