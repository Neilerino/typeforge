"""Adapter protocol for backend-specific type operations."""

from typing import Protocol, runtime_checkable

from returns.result import Result

from typeforge.semantics.errors import SemanticIssue
from typeforge.semantics.model import RecordShape


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
