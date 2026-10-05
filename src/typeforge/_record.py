"""Construct immutable record templates without reflecting application types."""

from collections.abc import Iterable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from types import GenericAlias
from typing import Self, get_args


@dataclass(frozen=True, slots=True, eq=False)
class FieldSymbol:
    """Identity of one field binding, independent of its authored spelling."""


class SymbolicField(GenericAlias):
    __slots__ = ()

    def __getattribute__(self, name: str) -> object:
        # GenericAlias forwards attributes to its origin. Field properties need
        # the binding on this instance rather than the class's property object.
        if name in {"name", "type"}:
            return object.__getattribute__(self, name)

        return super().__getattribute__(name)

    @property
    def name(self) -> GenericAlias:
        return GenericAlias(FieldNameTemplate, get_args(self))

    @property
    def type(self) -> GenericAlias:
        return GenericAlias(FieldTypeTemplate, get_args(self))

    def __bool__(self) -> bool:
        raise TypeError("symbolic field truthiness is unsupported; use Map")

    @classmethod
    def __class_getitem__(cls, arguments: tuple[object, ...]) -> Self:
        _field_symbol(arguments)
        return super().__new__(cls, cls, arguments)


class FieldNameTemplate:
    @classmethod
    def __class_getitem__(cls, arguments: tuple[object, ...]) -> GenericAlias:
        _field_symbol(arguments)
        return GenericAlias(cls, arguments)


class FieldTypeTemplate:
    @classmethod
    def __class_getitem__(cls, arguments: tuple[object, ...]) -> GenericAlias:
        _field_symbol(arguments)
        return GenericAlias(cls, arguments)


@dataclass(frozen=True, slots=True)
class _FieldSource:
    record: object
    binding: SymbolicField


_SOURCES: ContextVar[list[_FieldSource] | None] = ContextVar(
    "typeforge_record_sources", default=None
)


class Fields(GenericAlias):
    """Yield one symbolic field while Record constructs its reusable template."""

    __slots__ = ()

    @classmethod
    def __class_getitem__(cls, record: object) -> Self:
        return super().__new__(cls, cls, (record,))

    def __iter__(self) -> Iterator[SymbolicField]:
        sources = _SOURCES.get()
        if sources is None:
            raise TypeError("Fields must be consumed by Record")

        if sources:
            raise TypeError("Record currently requires one Fields iteration")

        binding = SymbolicField(SymbolicField, (FieldSymbol(),))
        sources.append(_FieldSource(get_args(self)[0], binding))
        yield binding


class RecordTemplate:
    @classmethod
    def __class_getitem__(cls, arguments: tuple[object, ...]) -> GenericAlias:
        if len(arguments) != 3:
            raise TypeError("invalid record template")

        return GenericAlias(cls, arguments)


def Record(fields: Iterable[object]) -> GenericAlias:
    """Consume construction immediately; specialization never replays iteration."""
    sources: list[_FieldSource] = []
    token = _SOURCES.set(sources)
    try:
        outputs = tuple(fields)
    finally:
        _SOURCES.reset(token)

    if len(sources) != 1 or len(outputs) != 1:
        raise TypeError("Record requires one unfiltered Fields iteration")

    source = sources[0]
    # Keep the record operand visible to Python's generic parameter substitution,
    # including when the transform drops every field.
    return GenericAlias(RecordTemplate, (source.record, source.binding, outputs[0]))


def _field_symbol(arguments: tuple[object, ...]) -> FieldSymbol:
    if len(arguments) != 1 or not isinstance(arguments[0], FieldSymbol):
        raise TypeError("invalid symbolic field binding")

    return arguments[0]
