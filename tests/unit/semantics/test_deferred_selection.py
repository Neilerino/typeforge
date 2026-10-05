"""Shared ordering can resume with backend observations before output execution."""

from dataclasses import dataclass, field

from returns.result import Failure, Result, Success

from tests.unit.semantics.test_migration_spec import NameTypeSystem
from typeforge import semantics as s


@dataclass
class Observer:
    decisions: tuple[Result[bool, s.SemanticIssue], ...]
    visited: list[s.Expression[str] | s.TypePattern[str]] = field(default_factory=list)

    def matches(
        self,
        test: s.Expression[str] | s.TypePattern[str],
        context: s.EvaluationContext[str],
    ) -> Result[bool, s.SemanticIssue]:
        self.visited.append(test)
        return self.decisions[len(self.visited) - 1]


def test_resumption_selects_once_without_evaluating_output_and_retains_bindings() -> (
    None
):
    cases = (
        s.CaseExpression(s.ExactTypePattern("bytes"), s.type_ref("bytes")),
        s.CaseExpression(s.ExactTypePattern("str"), s.KeyReference()),
        s.CaseExpression(s.ExactTypePattern("int"), s.type_ref("int")),
    )
    context = s.EvaluationContext(
        value=s.ResolvedType("float"),
        captures=((s.TypeSymbol((__name__,), "Item"), s.ResolvedType("str")),),
    )
    plan = s.DeferredMap(cases, s.type_ref("default"), context)
    observer = Observer((Success(False), Success(True)))
    evaluator = s.Evaluator(NameTypeSystem())
    selected = evaluator.select_deferred_map(plan, "raw-type", observer).unwrap()
    assert selected.case_index == 1
    assert selected.output is cases[1].output
    assert selected.context.value is context.value
    assert selected.context.captures is context.captures
    assert selected.context.input_type == s.ResolvedType("raw-type")
    assert observer.visited == [case.test for case in cases[:2]]
    assert evaluator.context.input_type is None
    assert plan.context.input_type is None


def test_predicates_use_bound_input_and_short_circuit_without_observation() -> None:
    predicate = s.AnyExpression(
        (
            s.EqualExpression(s.InputReference(), s.type_ref("int")),
            s.EqualExpression(s.KeyReference(), s.KeyReference()),
        )
    )
    output = s.type_ref("chosen")
    plan = s.DeferredMap(
        (s.CaseExpression(predicate, output),), None, s.EvaluationContext()
    )
    observer = Observer(())
    evaluator = s.Evaluator(NameTypeSystem())
    assert (
        evaluator.select_deferred_map(plan, "int", observer).unwrap().output is output
    )
    failure = evaluator.select_deferred_map(plan, "str", observer).failure()
    assert isinstance(failure, s.UnboundKeySemanticError)
    assert observer.visited == []


def test_observation_failure_keeps_identity_and_stops_selection() -> None:
    issue = s.SemanticAdapterError("observation failed")
    plan = s.DeferredMap(
        (s.CaseExpression(s.type_ref("int"), s.type_ref("str")),),
        s.type_ref("default"),
        s.EvaluationContext(),
    )
    observer = Observer((Failure(issue),))
    assert (
        s.Evaluator(NameTypeSystem())
        .select_deferred_map(plan, "int", observer)
        .failure()
        is issue
    )


def test_default_and_exhaustion_are_distinct_from_an_explicit_never_output() -> None:
    evaluator = s.Evaluator(NameTypeSystem())
    context = s.EvaluationContext[str]()
    empty = s.MapExpression(s.InputReference(), ())
    plan = s.DeferredMap((), None, context, expression=empty)
    failure = evaluator.select_deferred_map(plan, "int", Observer(())).failure()
    assert isinstance(failure, s.MapNoMatch)
    assert failure.expression is empty
    assert failure.subject == s.ResolvedType("int")
    default = evaluator.select_deferred_map(
        s.DeferredMap((), s.type_ref("Never"), context), "int", Observer(())
    ).unwrap()
    assert default.case_index is None
    assert default.output == s.type_ref("Never")


@dataclass
class DeferredTypes:
    plans: list[s.DeferredMap[str]] = field(default_factory=list)

    def defer(
        self, plan: s.DeferredMap[str]
    ) -> Result[str, s.SemanticIssue | s.MapNoMatch[str]]:
        self.plans.append(plan)
        return Success("deferred")


def test_deferred_backend_preserves_plans_in_templates_without_eager_bounds() -> None:
    deferred_types = DeferredTypes()
    expression = s.MapExpression(
        s.InputReference(),
        (s.CaseExpression(s.type_ref("str"), s.KeyReference()),),
    )
    template = s.ParameterizedTypeTemplate("list", (expression,))
    type_system = NameTypeSystem(
        parameterized_types=(
            ("list[deferred]", s.ParameterizedTypeShape("list", ("deferred",))),
        )
    )
    evaluator = s.Evaluator(type_system, deferred_types=deferred_types)
    assert evaluator.evaluate(template).unwrap() == s.ResolvedType("list[deferred]")
    assert len(deferred_types.plans) == 1
    assert deferred_types.plans[0].expression is expression
    assert deferred_types.plans[0].possible_output is None
