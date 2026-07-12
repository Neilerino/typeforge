from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NamedType:
    name: str
    bases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NeverType:
    pass


@dataclass(frozen=True, slots=True)
class UnionType:
    members: tuple[StaticType, ...]


@dataclass(frozen=True, slots=True)
class TypedDictField:
    name: str
    value: StaticType
    required: bool = True
    readonly: bool = False


@dataclass(frozen=True, slots=True)
class TypedDictShape:
    name: str | None
    fields: tuple[TypedDictField, ...]


type StaticType = NamedType | NeverType | UnionType | TypedDictShape

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
    return UnionType(tuple(flattened))
