import ast

from typeforge.verification.model import Guard, GuardMode


def recognize_guard(expression: ast.expr, controller: str) -> tuple[Guard, bool] | None:
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        recognized = recognize_guard(expression.operand, controller)
        return None if recognized is None else (recognized[0], not recognized[1])
    exact = _recognize_exact_type(expression, controller)
    if exact is not None:
        return exact
    instance = _recognize_isinstance(expression, controller)
    if instance is not None:
        return instance, True
    return _recognize_value(expression, controller)


def recognize_pattern(pattern: ast.pattern, controller: str) -> Guard | None:
    if isinstance(pattern, ast.MatchClass):
        return Guard(
            symbol=controller,
            type_names=(ast.unparse(pattern.cls),),
            mode=GuardMode.INSTANCE,
        )
    if isinstance(pattern, ast.MatchSingleton):
        return Guard(
            symbol=controller,
            type_names=(_literal_type(pattern.value),),
            mode=GuardMode.EXACT,
        )
    if isinstance(pattern, ast.MatchValue):
        value = _literal_expression_type(pattern.value)
        if value is not None:
            return Guard(controller, (value,), GuardMode.EXACT)
    if isinstance(pattern, ast.MatchOr):
        guards = tuple(
            guard
            for item in pattern.patterns
            if (guard := recognize_pattern(item, controller)) is not None
        )
        if len(guards) == len(pattern.patterns) and guards:
            mode = (
                GuardMode.INSTANCE
                if any(item.mode is GuardMode.INSTANCE for item in guards)
                else GuardMode.EXACT
            )
            return Guard(
                controller,
                tuple(type_name for guard in guards for type_name in guard.type_names),
                mode,
            )
    return None


def _recognize_exact_type(
    expression: ast.expr, controller: str
) -> tuple[Guard, bool] | None:
    if not isinstance(expression, ast.Compare) or len(expression.ops) != 1:
        return None
    left_type = _type_call_subject(expression.left)
    right_type = _type_call_subject(expression.comparators[0])
    left_name = _type_name(expression.left)
    right_name = _type_name(expression.comparators[0])
    operator = expression.ops[0]
    if isinstance(operator, ast.Is | ast.Eq | ast.IsNot | ast.NotEq):
        positive = isinstance(operator, ast.Is | ast.Eq)
        if left_type == controller and right_name is not None:
            return Guard(controller, (right_name,), GuardMode.EXACT), positive
        if right_type == controller and left_name is not None:
            return Guard(controller, (left_name,), GuardMode.EXACT), positive
    return None


def _recognize_isinstance(expression: ast.expr, controller: str) -> Guard | None:
    if not (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id == "isinstance"
        and len(expression.args) == 2
        and not expression.keywords
        and isinstance(expression.args[0], ast.Name)
        and expression.args[0].id == controller
    ):
        return None
    types = expression.args[1]
    items = types.elts if isinstance(types, ast.Tuple) else (types,)
    names = tuple(name for item in items if (name := _type_name(item)) is not None)
    if len(names) != len(items):
        return None
    return Guard(controller, names, GuardMode.INSTANCE)


def _recognize_value(
    expression: ast.expr, controller: str
) -> tuple[Guard, bool] | None:
    if not isinstance(expression, ast.Compare) or len(expression.ops) != 1:
        return None
    if not isinstance(expression.ops[0], ast.Is | ast.Eq | ast.IsNot | ast.NotEq):
        return None
    positive = isinstance(expression.ops[0], ast.Is | ast.Eq)
    left = expression.left
    right = expression.comparators[0]
    if isinstance(left, ast.Name) and left.id == controller:
        value = _literal_expression_type(right)
    elif isinstance(right, ast.Name) and right.id == controller:
        value = _literal_expression_type(left)
    else:
        return None
    return (
        (Guard(controller, (value,), GuardMode.EXACT), positive)
        if value is not None
        else None
    )


def _type_call_subject(expression: ast.expr) -> str | None:
    if not (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id == "type"
        and len(expression.args) == 1
        and not expression.keywords
        and isinstance(expression.args[0], ast.Name)
    ):
        return None
    return expression.args[0].id


def _type_name(expression: ast.expr) -> str | None:
    if isinstance(expression, ast.Name | ast.Attribute):
        return ast.unparse(expression)
    return None


def _literal_expression_type(expression: ast.expr) -> str | None:
    if isinstance(expression, ast.Constant):
        return _literal_type(expression.value)
    if isinstance(expression, ast.Attribute):
        return f"Literal[{ast.unparse(expression)}]"
    return None


def _literal_type(value: object) -> str:
    if value is None:
        return "None"
    return f"Literal[{value!r}]"
