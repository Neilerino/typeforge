"""Compiler adapter for backend-neutral semantic type operations."""

from dataclasses import dataclass

from returns.result import Failure, Result, Success

from typeforge.compiler.records import (
    NamedType,
    NeverType,
    StaticType,
    TypedDictField,
    TypedDictShape,
    UnionType,
    union_of,
)
from typeforge.semantics import (
    ExpectedRecordSemanticError,
    RecordFamily,
    RecordField,
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
                return Success(
                    all(_is_assignable(member, target) for member in source.members)
                )
            case _, UnionType():
                return Success(
                    any(_is_assignable(source, member) for member in target.members)
                )
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
        if not isinstance(value, TypedDictShape):
            return Failure(
                ExpectedRecordSemanticError(
                    f"{value!r} is not a supported compiler record"
                )
            )

        return Success(
            RecordShape(
                family=RecordFamily.TYPED_DICT,
                name=value.name,
                fields=tuple(
                    RecordField(
                        name=field.name,
                        value=field.value,
                        required=field.required,
                        readonly=field.readonly,
                    )
                    for field in value.fields
                ),
            )
        )


COMPILER_TYPE_SYSTEM = CompilerTypeSystem()


def typed_dict_shape(
    record: RecordShape[StaticType],
) -> Result[TypedDictShape, SemanticIssue]:
    """Convert a shared record result back to compiler emission data."""
    if record.family is not RecordFamily.TYPED_DICT:
        return Failure(
            ExpectedRecordSemanticError(
                "compiler record emission does not support "
                f"{record.family.value} records"
            )
        )

    return Success(
        TypedDictShape(
            name=record.name,
            fields=tuple(
                TypedDictField(
                    name=field.name,
                    value=field.value,
                    required=field.required,
                    readonly=field.readonly,
                )
                for field in record.fields
            ),
        )
    )
