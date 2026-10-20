"""Scoped scalar substitution and provenance-preserving specialization utilities."""

from typeforge.compiler.stub_ir import (
    CollectType,
    EachType,
    FixedTuple,
    HomogeneousTuple,
    StubTypeExpression,
    TypeApplication,
    TypeRewriteObserver,
    TypeVariable,
    UnionExpression,
    rewrite_type,
    walk_type,
)


def has_variable(expression: StubTypeExpression, variable: str) -> bool:
    return variable in collect_variable_names(expression)


def union_types(
    expressions: tuple[StubTypeExpression, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    members: list[StubTypeExpression] = []
    for expression in expressions:
        candidates = (
            expression.members
            if isinstance(expression, UnionExpression)
            else (expression,)
        )
        for candidate in candidates:
            if on_rewrite is not None and candidate is not expression:
                on_rewrite(expression, candidate)

            retained = next((member for member in members if member == candidate), None)
            if retained is None:
                members.append(candidate)
            elif on_rewrite is not None:
                for original, replacement in zip(
                    walk_type(candidate), walk_type(retained), strict=True
                ):
                    on_rewrite(original, replacement)

    if len(members) == 1:
        return members[0]

    return UnionExpression(tuple(members))


def fresh_type_parameter_names(
    base: str, count: int, reserved: tuple[str, ...]
) -> tuple[str, ...]:
    names: list[str] = []
    reserved_names = {type_parameter_name(item) for item in reserved}
    candidate_index = 1
    while len(names) < count:
        candidate = f"{base}{candidate_index}"
        candidate_index += 1
        if candidate in reserved_names:
            continue

        names.append(candidate)
        reserved_names.add(candidate)

    return tuple(names)


def type_parameter_name(declaration: str) -> str:
    return declaration.lstrip("*").split(":", 1)[0].split("=", 1)[0].strip()


def collect_variable_names(expression: StubTypeExpression) -> tuple[str, ...]:
    names: list[str] = []

    def visit(current: StubTypeExpression) -> None:
        if isinstance(current, TypeVariable):
            if current.name not in names:
                names.append(current.name)
        elif isinstance(current, TypeApplication):
            visit(current.constructor)
            for argument in current.arguments:
                visit(argument)
        elif isinstance(current, FixedTuple):
            for item in current.items:
                visit(item)
        elif isinstance(current, UnionExpression):
            for member in current.members:
                visit(member)
        elif isinstance(current, HomogeneousTuple | EachType | CollectType):
            visit(current.item)

    visit(expression)
    return tuple(names)


def substitute_scalar(
    expression: StubTypeExpression,
    variable: str,
    replacement: StubTypeExpression,
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    def replace_variable(current: StubTypeExpression) -> StubTypeExpression | None:
        if isinstance(current, TypeVariable):
            return replacement if current.name == variable else current

        # Each/Collect and Map bind their own variables; scalar substitution
        # must not descend through those boundaries.
        if isinstance(
            current, TypeApplication | FixedTuple | HomogeneousTuple | UnionExpression
        ):
            return None

        return current

    return rewrite_type(expression, replace_variable, on_rewrite=on_rewrite)
