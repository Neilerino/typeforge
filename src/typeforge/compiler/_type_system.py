"""Compiler adapter for backend-neutral semantic type operations."""

from dataclasses import dataclass

from returns.result import Failure, Result, Success

from typeforge.compiler.records import (
    NamedType,
    NeverType,
    StaticType,
    UnionType,
    union_of,
)
from typeforge.semantics import (
    ExpectedRecordSemanticError,
    ParameterizedTypeShape,
    RecordShape,
    SemanticIssue,
)


@dataclass(frozen=True, slots=True)
class CompilerTypeSystem:
    """Interpret semantic operations over compiler-owned static types."""

    def equal(self, left: StaticType, right: StaticType) -> Result[bool, SemanticIssue]:
        return Success(left == right)

    def assignable(
        self, source: StaticType, target: StaticType
    ) -> Result[bool, SemanticIssue]:
        match source, target:
            case NeverType(), _:
                return Success(True)
            case UnionType(), _:
                for member in source.members:
                    result = self.assignable(member, target)
                    if isinstance(result, Failure):
                        return result
                    if not result.unwrap():
                        return Success(False)
                return Success(True)
            case _, UnionType():
                for member in target.members:
                    result = self.assignable(source, member)
                    if isinstance(result, Failure):
                        return result
                    if result.unwrap():
                        return Success(True)
                return Success(False)
            case NamedType(), NamedType():
                return Success(
                    source.name == target.name
                    or target.name == "object"
                    or target.name in source.bases
                )
            case _:
                return Success(source == target)

    def union_members(
        self, value: StaticType
    ) -> Result[tuple[StaticType, ...], SemanticIssue]:
        match value:
            case NeverType():
                return Success(())
            case UnionType(members):
                return Success(members)
            case _:
                return Success((value,))

    def union(
        self, members: tuple[StaticType, ...]
    ) -> Result[StaticType, SemanticIssue]:
        return Success(union_of(*members))

    def record(
        self, value: StaticType
    ) -> Result[RecordShape[StaticType], SemanticIssue]:
        if not isinstance(value, RecordShape):
            return Failure(
                ExpectedRecordSemanticError(
                    f"{value!r} is not a supported compiler record"
                )
            )

        return Success(value)

    def inspect(
        self, value: StaticType
    ) -> Result[ParameterizedTypeShape[StaticType] | None, SemanticIssue]:
        raise NotImplementedError

    def build(
        self, shape: ParameterizedTypeShape[StaticType]
    ) -> Result[StaticType, SemanticIssue]:
        raise NotImplementedError


COMPILER_TYPE_SYSTEM = CompilerTypeSystem()
