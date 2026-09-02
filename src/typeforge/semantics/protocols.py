"""Adapter protocol for backend-specific type operations."""

from typing import Protocol, runtime_checkable

from returns.result import Result

from typeforge.semantics.domain.exceptions import SemanticIssue
from typeforge.semantics.domain.models import ParameterizedTypeShape, RecordShape


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
