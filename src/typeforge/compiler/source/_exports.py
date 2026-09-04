"""Parsing of statically declared authored module exports."""

import ast


def static_export_names(expression: ast.expr) -> tuple[str, ...] | None:
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
