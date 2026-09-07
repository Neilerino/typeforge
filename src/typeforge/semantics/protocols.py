"""Adapter protocol for backend-specific type operations."""

from typing import Protocol, runtime_checkable

from returns.result import Result

from typeforge.semantics.domain.exceptions import SemanticIssue
from typeforge.semantics.domain.models import (
    DeferredMap,
    EvaluationContext,
    Expression,
    MapNoMatch,
    NoMatchDecision,
    ParameterizedTypeShape,
    RecordShape,
    TypePattern,
)


class DeferredTypes[T](Protocol):
    """Represent a deferred plan as a backend type, preserving later execution."""

    def defer(
        self, plan: DeferredMap[T]
    ) -> Result[T, SemanticIssue | MapNoMatch[T]]: ...


class InputObserver[T](Protocol):
    """Observe a non-predicate case on demand; raw values stay in the adapter."""

    def matches(
        self, test: Expression[T] | TypePattern[T], context: EvaluationContext[T]
    ) -> Result[bool, SemanticIssue]: ...


class EvaluationPolicy[T](Protocol):
    """Consumer acceptance rules; matching and output selection remain shared."""

    def no_match(self, outcome: MapNoMatch[T]) -> NoMatchDecision:
        """Decide explicitly, including whether the path is speculative.

        Expected rejection is a decision, not an exception. The evaluator returns
        the rejected outcome as a typed failure, retaining its expression/context.
        """
        ...


@runtime_checkable
class TypeSystem[T](Protocol):
    """Operations that vary between compiler and runtime type adapters."""

    def equal(self, left: T, right: T) -> Result[bool, SemanticIssue]:
        """Return whether two backend-specific types are equal."""
        ...

    def assignable(self, source: T, target: T) -> Result[bool, SemanticIssue]:
        """Return whether source is assignable to target."""
        ...

    def union_members(self, value: T) -> Result[tuple[T, ...], SemanticIssue]:
        """Decompose in native order; Never is empty, non-unions are singletons."""
        ...

    def union(self, members: tuple[T, ...]) -> Result[T, SemanticIssue]:
        """Normalize members; an empty tuple represents Never."""
        ...

    def record(self, value: T) -> Result[RecordShape[T], SemanticIssue]:
        """Describe value without erasing its record family."""
        ...

    def inspect(
        self, value: T
    ) -> Result[ParameterizedTypeShape[T] | None, SemanticIssue]:
        """Return the origin and arguments of a parameterized type, if present."""
        ...

    def build(self, shape: ParameterizedTypeShape[T]) -> Result[T, SemanticIssue]:
        """Build a backend type from a parameterized type shape."""
        ...
