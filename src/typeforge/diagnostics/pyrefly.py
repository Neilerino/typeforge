import re

from typeforge.diagnostics.explain import explain_problem
from typeforge.diagnostics.model import CheckerDetail, ProblemKind, TypeProblem
from typeforge.diagnostics.provenance import collect_authored_callables
from typeforge.diagnostics.render import render_compact

_NO_MATCHING_OVERLOAD = re.compile(
    r"^No matching overload found for function `([^`]+)` "
    r"called with arguments: \((.*)\)$"
)


def present_pyrefly_message(source: str, code: str | None, message: str) -> str:
    problem = parse_pyrefly_problem(code, message)
    if problem is None:
        return message
    explanation = explain_problem(problem, collect_authored_callables(source))
    return render_compact(explanation) if explanation is not None else message


def parse_pyrefly_problem(code: str | None, message: str) -> TypeProblem | None:
    if code != "no-matching-overload":
        return None
    first_line, _, _ = message.partition("\n")
    match = _NO_MATCHING_OVERLOAD.fullmatch(first_line)
    if match is None:
        return None
    received = _split_types(match.group(2))
    if received is None:
        return None
    return TypeProblem(
        kind=ProblemKind.NO_MATCHING_OVERLOAD,
        callable_name=match.group(1),
        received=received,
        checker_detail=CheckerDetail(
            checker="pyrefly",
            code=code,
            message=message,
        ),
    )


def _split_types(source: str) -> tuple[str, ...] | None:
    if not source.strip():
        return ()
    parts: list[str] = []
    start = 0
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    quote: str | None = None
    escaped = False
    for index, character in enumerate(source):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character in "([{":
            stack.append(character)
        elif character in ")]}":
            if not stack or stack.pop() != pairs[character]:
                return None
        elif character == "," and not stack:
            part = source[start:index].strip()
            if not part:
                return None
            parts.append(part)
            start = index + 1
    if stack or quote is not None:
        return None
    final = source[start:].strip()
    if not final:
        return None
    parts.append(final)
    return tuple(parts)
