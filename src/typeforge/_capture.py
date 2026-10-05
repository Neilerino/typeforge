"""Immutable capture declarations that work in ordinary Python typing trees."""

from dataclasses import dataclass
from types import GenericAlias
from typing import Self


@dataclass(frozen=True, slots=True, eq=False)
class CaptureSymbol:
    """Declaration identity is independent of its diagnostic label."""

    name: str


class Capture(GenericAlias):
    """Declare a named token; matching binds it within one evaluation."""

    __slots__ = ()

    def __new__(cls, name: object) -> Self:
        if not isinstance(name, str) or not name:
            raise TypeError("Capture requires a nonempty string name")

        return super().__new__(cls, cls, (CaptureSymbol(name),))

    def __bool__(self) -> bool:
        raise TypeError("capture truthiness is unsupported; use Map for type selection")
