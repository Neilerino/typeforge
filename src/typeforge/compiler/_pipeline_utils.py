"""AST inspection and import-handling utilities for the compiler pipeline."""

import ast
from pathlib import Path

from returns.result import Failure, Result, Success

from typeforge.compiler._pipeline_models import (
    ModuleVariables,
    UnsupportedPublicDeclaration,
)
from typeforge.compiler.source import SourceModule, static_export_names
from typeforge.compiler.stub_ir import ImportFrom, TypeName, VariableDeclaration


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
                if static_export_names(value) is not None:
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
    declarations: list[VariableDeclaration] = []
    requires_any = False
    for statement in module.body:
        if isinstance(statement, ast.AnnAssign):
            if not isinstance(statement.target, ast.Name):
                continue
            name = statement.target.id
            if name.startswith("_"):
                continue
            annotation = ast.unparse(statement.annotation)
            declarations.append(VariableDeclaration(name, TypeName(annotation)))
            requires_any = requires_any or _annotation_contains_any(annotation)
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
                declarations.append(
                    VariableDeclaration(name, TypeName(statement.type_comment))
                )
                requires_any = requires_any or _annotation_contains_any(
                    statement.type_comment
                )
            continue
        for target in statement.targets:
            bindings = _infer_assignment_bindings(target, statement.value)
            for name, annotation in bindings:
                if name.startswith("_"):
                    continue
                declarations.append(VariableDeclaration(name, TypeName(annotation)))
                requires_any = requires_any or _annotation_contains_any(annotation)
    imports = (ImportFrom("typing", ("Any",)),) if requires_any else ()
    return ModuleVariables(tuple(declarations), imports)


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
