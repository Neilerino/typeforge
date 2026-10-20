from dataclasses import dataclass
from typing import Literal, TypeIs

from typeforge.semantics import RecordShape


@dataclass(frozen=True, slots=True)
class NamedType:
    name: str
    bases: tuple[str, ...] = ()
    identity: str | None = None


@dataclass(frozen=True, slots=True)
class NeverType:
    pass


@dataclass(frozen=True, slots=True)
class ParameterizedType:
    origin: StaticType
    arguments: tuple[StaticType, ...]


@dataclass(frozen=True, slots=True)
class UnpackedType:
    item: StaticType


@dataclass(frozen=True, slots=True)
class VariadicType:
    """A compiler arity marker awaiting finite specialization."""

    kind: Literal["Each", "Collect"]
    item: StaticType


@dataclass(frozen=True, slots=True, init=False)
class UnionType:
    members: tuple[StaticType, ...]

    def __init__(self, *members: StaticType) -> None:
        object.__setattr__(self, "members", members)


type StaticType = (
    NamedType
    | NeverType
    | ParameterizedType
    | UnpackedType
    | VariadicType
    | UnionType
    | RecordShape[StaticType]
)

NEVER = NeverType()


def union_of(*members: StaticType) -> StaticType:
    flattened: list[StaticType] = []
    for member in members:
        candidates = member.members if isinstance(member, UnionType) else (member,)
        for candidate in candidates:
            if isinstance(candidate, NeverType) or candidate in flattened:
                continue

            flattened.append(candidate)

    if not flattened:
        return NEVER

    if len(flattened) == 1:
        return flattened[0]

    return UnionType(*flattened)


def is_static(value: object) -> TypeIs[StaticType]:
    return isinstance(
        value,
        NamedType
        | NeverType
        | ParameterizedType
        | UnpackedType
        | VariadicType
        | UnionType
        | RecordShape,
    )
