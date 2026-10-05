import pytest
from returns.result import Failure, Success

from tests.unit.semantics.test_migration_spec import NameTypeSystem
from typeforge import semantics as s


class RecordingPolicy:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.outcomes: list[s.MapNoMatch[str]] = []

    def no_match(self, outcome: s.MapNoMatch[str]) -> s.NoMatchDecision:
        self.outcomes.append(outcome)
        return s.NoMatchDecision.REJECT if self.reject else s.NoMatchDecision.ACCEPT


def test_policy_rejection_is_a_typed_failure_and_stops_later_evaluation() -> None:
    unmatched = s.MapExpression(s.TypeReference("int"), ())
    expression = s.UnionExpression((unmatched, s.KeyReference()))
    policy = RecordingPolicy(reject=True)

    result = s.Evaluator(NameTypeSystem(), policy=policy).evaluate(expression)

    assert isinstance(result, Failure)
    assert result.failure() is policy.outcomes[0]
    assert result.failure().expression is unmatched
    assert len(policy.outcomes) == 1


def test_default_rejects_and_explicit_acceptance_preserves_never() -> None:
    expression = s.MapExpression(s.TypeReference("int"), ())
    policy = RecordingPolicy()
    expected = Success(s.ResolvedType("Never"))

    assert isinstance(s.evaluate(expression, NameTypeSystem()), Failure)
    assert isinstance(s.Evaluator(NameTypeSystem()).evaluate(expression), Failure)
    assert s.Evaluator(NameTypeSystem(), policy=policy).evaluate(expression) == expected
    assert policy.outcomes[0].subject == s.ResolvedType("int")
    assert policy.outcomes[0].context.mode is s.EvaluationMode.DEFINITE


@pytest.mark.parametrize(
    "expression",
    [
        s.MapExpression(s.TypeReference("int"), (), s.TypeReference("Never")),
        s.MapExpression(
            s.TypeReference("int"),
            (s.CaseExpression(s.ExactTypePattern("int"), s.TypeReference("Never")),),
        ),
    ],
)
def test_explicit_never_outputs_do_not_invoke_no_match_policy(
    expression: s.Expression[str],
) -> None:
    policy = RecordingPolicy(reject=True)
    assert s.Evaluator(NameTypeSystem(), policy=policy).evaluate(expression) == Success(
        s.ResolvedType("Never")
    )
    assert policy.outcomes == []


def test_nested_no_match_preserves_authored_expression_and_bindings() -> None:
    inner = s.MapExpression(s.ValueReference(), ())
    outer = s.MapExpression(
        s.TypeReference("int"),
        (s.CaseExpression(s.ExactTypePattern("int"), inner),),
    )
    context = s.EvaluationContext(value=s.ResolvedType("bytes"))
    policy = RecordingPolicy(reject=True)

    result = s.Evaluator(NameTypeSystem(), policy=policy, context=context).evaluate(
        outer
    )

    assert result == Failure(s.MapNoMatch(inner, s.ResolvedType("bytes"), context))
    assert policy.outcomes[0].expression is inner


def test_unvisited_output_never_invokes_policy() -> None:
    expression = s.MapExpression(
        s.TypeReference("int"),
        (
            s.CaseExpression(
                s.ExactTypePattern("bytes"),
                s.MapExpression(s.TypeReference("int"), ()),
            ),
        ),
        s.TypeReference("str"),
    )
    policy = RecordingPolicy(reject=True)

    assert s.Evaluator(NameTypeSystem(), policy=policy).evaluate(expression) == Success(
        s.ResolvedType("str")
    )
    assert policy.outcomes == []


def test_indeterminate_selected_output_and_remainder_are_speculative() -> None:
    subject = s.UnresolvedType("T", s.TypeSymbol(("Model",), "T"))
    inner = s.MapExpression(s.TypeReference("bytes"), ())
    outer = s.MapExpression(
        s.TypeValueReference(subject),
        (s.CaseExpression(s.ExactTypePattern("int"), inner),),
    )
    policy = RecordingPolicy()
    evaluator = s.Evaluator(NameTypeSystem(), policy=policy)

    assert isinstance(evaluator.evaluate(outer).unwrap(), s.IndeterminateType)
    assert [outcome.expression for outcome in policy.outcomes] == [inner, outer]
    assert policy.outcomes[1].subject is subject
    assert all(
        outcome.context.mode is s.EvaluationMode.SPECULATIVE
        for outcome in policy.outcomes
    )
    # Speculation in one call must not change the next call's interpretation.
    evaluator.evaluate(inner).unwrap()
    assert policy.outcomes[-1].context.mode is s.EvaluationMode.DEFINITE


def test_deferred_output_bounds_are_speculative_but_resumption_is_definite() -> None:
    inner = s.MapExpression(s.TypeReference("bytes"), ())
    expression = s.MapExpression(
        s.InputReference(),
        (s.CaseExpression(s.ExactTypePattern("int"), inner),),
    )
    policy = RecordingPolicy()
    evaluator = s.Evaluator(NameTypeSystem(), policy=policy)

    deferred = evaluator.evaluate(expression).unwrap()
    assert isinstance(deferred, s.DeferredMap)
    assert policy.outcomes[0].context.mode is s.EvaluationMode.SPECULATIVE
    assert deferred.context.mode is s.EvaluationMode.DEFINITE

    context = s.EvaluationContext(input_type=s.ResolvedType("int"))
    evaluator.with_context(context).evaluate(expression).unwrap()
    assert policy.outcomes[-1].context.mode is s.EvaluationMode.DEFINITE


@pytest.mark.parametrize("operator", [s.AllExpression, s.AnyExpression])
def test_conditions_after_an_indeterminate_operand_are_speculative(
    operator: type,
) -> None:
    unknown = s.TypeValueReference(s.UnresolvedType("T", s.TypeSymbol((), "T")))
    inner = s.MapExpression(s.TypeReference("int"), ())
    expression = operator(
        (
            s.EqualExpression(unknown, s.TypeReference("int")),
            s.EqualExpression(inner, s.TypeReference("Never")),
        )
    )
    policy = RecordingPolicy()

    s.Evaluator(NameTypeSystem(), policy=policy).evaluate(expression).unwrap()

    assert policy.outcomes[0].context.mode is s.EvaluationMode.SPECULATIVE


def test_child_evaluator_does_not_change_parent_bindings() -> None:
    evaluator = s.Evaluator(NameTypeSystem())
    expression = s.ValueReference()
    child = evaluator.with_context(s.EvaluationContext(value=s.ResolvedType("int")))
    assert child.evaluate(expression) == Success(s.ResolvedType("int"))
    result = evaluator.evaluate(expression)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), s.UnboundValueSemanticError)


def test_children_share_dependencies_and_keep_sibling_contexts_after_failure() -> None:
    policy = RecordingPolicy(reject=True)
    type_system = NameTypeSystem()
    parent_context = s.EvaluationContext(value=s.ResolvedType("int"))
    parent = s.Evaluator(type_system, policy=policy, context=parent_context)
    child_context = s.EvaluationContext(value=s.ResolvedType("bytes"))
    child = parent.with_context(child_context)
    sibling = parent.with_context(s.EvaluationContext(value=s.ResolvedType("str")))

    assert child is not parent
    assert child.type_system is type_system
    unmatched = s.MapExpression(s.ValueReference(), ())
    assert child.evaluate(unmatched) == Failure(
        s.MapNoMatch(unmatched, s.ResolvedType("bytes"), child_context)
    )
    assert policy.outcomes[0].context is child_context
    assert parent.context is parent_context
    assert parent.evaluate(s.ValueReference()) == Success(s.ResolvedType("int"))
    assert sibling.evaluate(s.ValueReference()) == Success(s.ResolvedType("str"))
    assert child.evaluate(s.ValueReference()) == Success(s.ResolvedType("bytes"))


def test_evaluator_context_cannot_be_rebound() -> None:
    evaluator = s.Evaluator(NameTypeSystem())
    with pytest.raises(AttributeError):
        evaluator.context = s.EvaluationContext(value=s.ResolvedType("int"))


def test_reentrant_child_evaluation_preserves_active_parent_context() -> None:
    class ReentrantPolicy:
        def no_match(self, outcome: s.MapNoMatch[str]) -> s.NoMatchDecision:
            child = evaluator.with_context(
                s.EvaluationContext(value=s.ResolvedType("bytes"))
            )
            assert child.evaluate(s.ValueReference()) == Success(
                s.ResolvedType("bytes")
            )
            return s.NoMatchDecision.ACCEPT

    evaluator = s.Evaluator(
        NameTypeSystem(),
        policy=ReentrantPolicy(),
        context=s.EvaluationContext(value=s.ResolvedType("int")),
    )
    expression = s.UnionExpression(
        (s.MapExpression(s.TypeReference("str"), ()), s.ValueReference())
    )

    assert evaluator.evaluate(expression) == Success(s.ResolvedType("int"))


def test_unexpected_policy_exception_propagates_with_identity() -> None:
    issue = RuntimeError("unexpected")

    class BrokenPolicy:
        def no_match(self, outcome: s.MapNoMatch[str]) -> s.NoMatchDecision:
            raise issue

    with pytest.raises(RuntimeError) as captured:
        s.Evaluator(NameTypeSystem(), policy=BrokenPolicy()).evaluate(
            s.MapExpression(s.TypeReference("int"), ())
        )

    assert captured.value is issue
