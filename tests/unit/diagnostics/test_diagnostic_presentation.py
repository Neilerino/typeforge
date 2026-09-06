import ast
from pathlib import Path

import pytest

from typeforge.compiler.pipeline import compile_source, describe_authored_callables
from typeforge.diagnostics import (
    AuthoredCallable,
    CheckerDetail,
    Explanation,
    ProblemKind,
    TypeProblem,
    explain_problem,
    parse_pyrefly_problem,
    present_pyrefly_message,
)
from typeforge.overlay import transform_source
from typeforge.proxy.model import JsonObject
from typeforge.proxy.pyrefly import present_pyrefly_diagnostic

SOURCE = """
from typeforge import Collect, Each


class World:
    def query[T](
        self,
        *components: Each[type[T]],
    ) -> Collect[T]: ...
""".lstrip()

MESSAGE = """No matching overload found for function `World.query` \
called with arguments: (dict[str, int])
  Possible overloads:
    () -> tuple[int] | None
    (components_1: type[T1], /) -> tuple[int, T1] | None
  Argument `dict[str, int]` is not assignable to parameter `components_1`
""".rstrip()


def test_diagnostics_reuse_the_compiled_callable_without_reparsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = transform_source(SOURCE, maximum_arity=1).unwrap()
    diagnostic: JsonObject = {"code": "no-matching-overload", "message": MESSAGE}

    def unexpected_parse(*args: object, **kwargs: object) -> ast.Module:
        raise AssertionError("diagnostic presentation must reuse compilation")

    with monkeypatch.context() as patch:
        patch.setattr(ast, "parse", unexpected_parse)
        presented = present_pyrefly_diagnostic(
            diagnostic, document, document.mappings[0].authored
        )

    assert presented["message"] == (
        "Invalid call to `World.query`\n\n"
        "Received: `dict[str, int]`\n"
        "Expected: `*components: Each[type[T]]`\n\n"
        "`components` expects type objects rather than instances or other values."
    )


def test_parses_nested_argument_types_without_splitting_inner_commas() -> None:
    message = (
        "No matching overload found for function `build` called with arguments: "
        "(dict[str, tuple[int, str]], Literal['a,b'])"
    )

    problem = parse_pyrefly_problem("no-matching-overload", message)

    assert problem is not None
    assert problem.received == (
        "dict[str, tuple[int, str]]",
        "Literal['a,b']",
    )


def test_presents_generated_overloads_as_the_authored_signature() -> None:
    plan = compile_source(SOURCE, Path("world.py"), maximum_arity=1).unwrap()

    presented = present_pyrefly_message(
        describe_authored_callables(plan), "no-matching-overload", MESSAGE
    )

    assert presented == (
        "Invalid call to `World.query`\n\n"
        "Received: `dict[str, int]`\n"
        "Expected: `*components: Each[type[T]]`\n\n"
        "`components` expects type objects rather than instances or other values."
    )
    assert "Possible overloads" not in presented


def test_preserves_checker_message_without_unambiguous_provenance() -> None:
    ambiguous = f"{SOURCE}\n{SOURCE}"
    plan = compile_source(ambiguous, Path("world.py"), maximum_arity=1).unwrap()
    callables = describe_authored_callables(plan)

    assert (
        present_pyrefly_message(callables, "no-matching-overload", MESSAGE) == MESSAGE
    )
    assert present_pyrefly_message((), "other", MESSAGE) == MESSAGE
    assert (
        present_pyrefly_message(callables, "no-matching-overload", "changed format")
        == "changed format"
    )


def test_explanation_rules_are_ordered_and_replaceable() -> None:
    problem = TypeProblem(
        kind=ProblemKind.NO_MATCHING_OVERLOAD,
        callable_name="World.query",
        received=("int",),
        checker_detail=CheckerDetail("pyrefly", "no-matching-overload", MESSAGE),
    )

    def custom_rule(
        problem: TypeProblem,
        callables: tuple[AuthoredCallable, ...],
    ) -> Explanation | None:
        del callables
        return Explanation(
            title=f"Custom: {problem.callable_name}",
            received=problem.received,
            expected=("Position",),
            reasons=(),
            checker_detail=problem.checker_detail,
        )

    explanation = explain_problem(problem, (), rules=(custom_rule,))

    assert explanation is not None
    assert explanation.title == "Custom: World.query"
