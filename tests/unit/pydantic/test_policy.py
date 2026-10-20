import pytest
from returns.result import Failure

from tests.unit.semantics.test_migration_spec import NameTypeSystem
from typeforge import semantics as s
from typeforge.pydantic._policy import (
    InputTestKind,
    generic_fallback,
    input_test_issue,
    no_match_issue,
)

FIELD = s.TypeSymbol(("test-field",), "field")


@pytest.mark.parametrize(
    ("default", "constraints", "bound", "expected"),
    [
        ("default", ("first", "second"), "bound", ("default",)),
        (None, ("first", "second"), "bound", ("first", "second")),
        (None, (), "bound", ("bound",)),
        (None, (), None, ("Any",)),
        ("", (), "bound", ("",)),
    ],
)
def test_generic_fallback_precedence_from_adapted_parameter_facts(
    default: str | None,
    constraints: tuple[str, ...],
    bound: str | None,
    expected: tuple[str, ...],
) -> None:
    assert (
        generic_fallback(
            default=default, constraints=constraints, bound=bound, any_type="Any"
        )
        == expected
    )


def test_no_match_issue_keeps_operands_available_before_diagnostic_presentation() -> (
    None
):
    expression, subject = object(), object()
    issue = no_match_issue(expression, subject, uses_generic_fallback=True)

    assert issue.code == "map_no_match"
    assert issue.expression is expression
    assert issue.subject is subject
    assert issue.uses_generic_fallback is True


def test_policy_accepts_speculative_no_match_but_rejects_the_selected_path() -> None:
    unmatched = s.MapExpression(s.TypeReference("bytes"), ())
    expression = s.MapExpression(
        s.InputReference(),
        (s.CaseExpression(s.ExactTypePattern("int"), unmatched),),
    )
    evaluator = s.Evaluator(NameTypeSystem())

    deferred = evaluator.evaluate(expression).unwrap()
    assert isinstance(deferred, s.DeferredMap)
    assert deferred.possible_output is not None
    assert deferred.possible_output.value == "Never"

    result = evaluator.with_context(
        s.EvaluationContext(input_type=s.ResolvedType("int"))
    ).evaluate(expression)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), s.MapNoMatch)
    assert result.failure().expression is unmatched


def test_speculative_policy_does_not_suppress_unrelated_semantic_failures() -> None:
    expression = s.MapExpression(
        s.InputReference(),
        (s.CaseExpression(s.ExactTypePattern("int"), s.FieldNameReference(FIELD)),),
    )
    result = s.Evaluator(NameTypeSystem()).evaluate(expression)

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), s.UnboundFieldSemanticError)


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        (InputTestKind.TYPE, None),
        (InputTestKind.INPUT, None),
        (InputTestKind.PREDICATE, None),
        (InputTestKind.PARAMETERIZED, "unsupported_runtime_pattern"),
        (InputTestKind.UNBOUND_FIELD, "unbound_field"),
        (InputTestKind.UNSUPPORTED, "unsupported_runtime_pattern"),
    ],
)
def test_input_admissibility_uses_frontend_facts_without_observing_a_value(
    kind: InputTestKind,
    code: str | None,
) -> None:
    expression = object()
    issue = input_test_issue(kind, expression)
    if code is None:
        assert issue is None
    else:
        assert issue is not None
        assert issue.code == code
        assert issue.expression is expression
