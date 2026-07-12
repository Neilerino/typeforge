from typeforge.diagnostics.model import (
    AuthoredCallable,
    AuthoredParameter,
    AuthoredParameterKind,
    Explanation,
    ExplanationRule,
    ProblemKind,
    TypeProblem,
)


def explain_problem(
    problem: TypeProblem,
    callables: tuple[AuthoredCallable, ...],
    rules: tuple[ExplanationRule, ...] | None = None,
) -> Explanation | None:
    active_rules = DEFAULT_EXPLANATION_RULES if rules is None else rules
    for rule in active_rules:
        explanation = rule(problem, callables)
        if explanation is not None:
            return explanation
    return None


def explain_authored_overload(
    problem: TypeProblem,
    callables: tuple[AuthoredCallable, ...],
) -> Explanation | None:
    if problem.kind is not ProblemKind.NO_MATCHING_OVERLOAD:
        return None
    matches = tuple(
        candidate
        for candidate in callables
        if _matches_name(problem.callable_name, candidate.display_name)
    )
    if len(matches) != 1:
        return None
    callable_ = matches[0]
    parameters = tuple(
        parameter
        for index, parameter in enumerate(callable_.parameters)
        if not (index == 0 and parameter.name in {"self", "cls"})
    )
    reasons = _reasons(parameters)
    return Explanation(
        title=f"Invalid call to `{problem.callable_name}`",
        received=problem.received,
        expected=tuple(_format_parameter(parameter) for parameter in parameters),
        reasons=reasons,
        checker_detail=problem.checker_detail,
    )


def _matches_name(checker_name: str, authored_name: str) -> bool:
    return checker_name == authored_name or checker_name.endswith(f".{authored_name}")


def _format_parameter(parameter: AuthoredParameter) -> str:
    prefix = ""
    if parameter.kind is AuthoredParameterKind.VAR_POSITIONAL:
        prefix = "*"
    elif parameter.kind is AuthoredParameterKind.VAR_KEYWORD:
        prefix = "**"
    annotation = f": {parameter.annotation}" if parameter.annotation else ""
    default = " = ..." if parameter.has_default else ""
    return f"{prefix}{parameter.name}{annotation}{default}"


def _reasons(parameters: tuple[AuthoredParameter, ...]) -> tuple[str, ...]:
    type_parameters = tuple(
        parameter
        for parameter in parameters
        if parameter.annotation is not None and "type[" in parameter.annotation
    )
    if len(type_parameters) != 1:
        return ("The supplied arguments do not match this authored signature.",)
    parameter = type_parameters[0]
    return (
        f"`{parameter.name}` expects type objects rather than instances or other "
        "values.",
    )


DEFAULT_EXPLANATION_RULES: tuple[ExplanationRule, ...] = (explain_authored_overload,)
