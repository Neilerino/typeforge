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
        return Success(_equal(left, right))

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


def _equal(left: StaticType, right: StaticType) -> bool:
    match left, right:
        case UnionType(left_members), UnionType(right_members):
            return all(
                any(_equal(member, candidate) for candidate in right_members)
                for member in left_members
            ) and all(
                any(_equal(member, candidate) for candidate in left_members)
                for member in right_members
            )
        case ParameterizedType(left_origin, left_args), ParameterizedType(
            right_origin, right_args
        ):
            return (
                _equal(left_origin, right_origin)
                and len(left_args) == len(right_args)
                and all(
                    _equal(a, b) for a, b in zip(left_args, right_args, strict=True)
                )
            )
        case _:
            return left == right


def _assignable(source: StaticType, target: StaticType) -> bool:
    match source, target:
        case NeverType(), _:
            return True
        case _, NamedType(name="object"):
            return True
        case UnionType(members), _:
            return all(_assignable(member, target) for member in members)
        case _, UnionType(members):
            return any(_assignable(source, member) for member in members)
        case NamedType(), NamedType():
            if source.name in {"Any", "typing.Any", "typing_extensions.Any"}:
                return True

            if target.name in {"Any", "typing.Any", "typing_extensions.Any"}:
                return True

            compatible_builtins = {
                "bool": {"int", "float", "complex"},
                "int": {"float", "complex"},
                "float": {"complex"},
            }
            return (
                source.name == target.name
                or target.name in source.bases
                or any(
                    target.name in compatible_builtins.get(name, set())
                    for name in (source.name, *source.bases)
                )
            )
        case _:
            return source == target


COMPILER_TYPE_SYSTEM = CompilerTypeSystem()
