from typing import Annotated, TypeVar

import pytest
from returns.result import Failure

from typeforge import Case, Default, Equal, Map
from typeforge import semantics as s
from typeforge.pydantic._errors import SchemaIssue
from typeforge.pydantic._frontend import adapt_annotation
from typeforge.pydantic._type_system import RUNTIME_TYPE_SYSTEM


def test_nested_adaptation_preserves_authored_origins_and_opaque_metadata() -> None:
    metadata = object()
    predicate = Equal[int, int]
    inner = Map[str, Case[str, bytes]]
    outer = Map[int, Case[predicate, inner], Default[float]]
    source = Annotated[outer, metadata]

    adapted = adapt_annotation(source).unwrap()

    assert adapted.origins[id(adapted.expression)] is source
    assert isinstance(adapted.expression, s.AnnotatedExpression)
    assert adapted.expression.metadata[0].annotation is metadata
    expression = adapted.expression.value
    assert isinstance(expression, s.MapExpression)
    assert adapted.origins[id(expression)] is outer
    assert adapted.origins[id(expression.subject)] is int
    assert adapted.origins[id(expression.cases[0].test)] is predicate
    assert adapted.origins[id(expression.cases[0].output)] is inner
    assert adapted.origins[id(expression.default)] is float


def test_failed_and_repeated_adaptations_do_not_share_origins() -> None:
    source = Map[int, Case[int, str]]
    first = adapt_annotation(source).unwrap()
    origins = dict(first.origins)
    invalid = Map[int, Default[str], Case[int, bytes]]

    failed = adapt_annotation(invalid)
    assert isinstance(failed, Failure)
    assert isinstance(failed.failure(), SchemaIssue)
    assert failed.failure().expression is invalid
    second = adapt_annotation(source).unwrap()
    assert first.origins == origins
    assert second.origins is not first.origins
    assert second.expression is not first.expression
    assert id(first.expression) not in second.origins


def test_adaptation_preserves_modeled_adapter_failure_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = s.SemanticAdapterError("fallback union failed")

    def fail(members: object) -> Failure[s.SemanticIssue]:
        return Failure(failure)

    monkeypatch.setattr(RUNTIME_TYPE_SYSTEM, "union", fail)
    result = adapt_annotation(TypeVar("T", bound=int))

    assert isinstance(result, Failure)
    assert result.failure() is failure


def test_unexpected_adaptation_failure_propagates_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = RuntimeError("unexpected reflection failure")

    def fail(members: object) -> object:
        raise failure

    monkeypatch.setattr(RUNTIME_TYPE_SYSTEM, "union", fail)
    with pytest.raises(RuntimeError) as captured:
        adapt_annotation(TypeVar("T", bound=int))

    assert captured.value is failure
