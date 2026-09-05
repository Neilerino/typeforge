"""Compiler adapter for backend-neutral semantic type operations."""

from dataclasses import dataclass

from returns.result import Failure, Result, Success

from typeforge.compiler.semantic_adapter._types import (
    NamedType,
    NeverType,
    ParameterizedType,
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
        return Success(_assignable(source, target))

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
        if isinstance(value, ParameterizedType):
            return Success(ParameterizedTypeShape(value.origin, value.arguments))

        return Success(None)

    def build(
        self, shape: ParameterizedTypeShape[StaticType]
    ) -> Result[StaticType, SemanticIssue]:
        return Success(ParameterizedType(shape.origin, shape.arguments))


def _assignable(source: StaticType, target: StaticType) -> bool:
    match source, target:
        case NeverType(), _:
            return True
        case UnionType(members), _:
            return all(_assignable(member, target) for member in members)
        case _, UnionType(members):
            return any(_assignable(source, member) for member in members)
        case NamedType(), NamedType():
            return (
                source.name == target.name
                or target.name == "object"
                or target.name in source.bases
            )
        case _:
            return source == target


COMPILER_TYPE_SYSTEM = CompilerTypeSystem()
