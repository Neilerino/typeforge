"""Backend-neutral facts for the supported generic compatibility frontier."""

from dataclasses import dataclass
from enum import StrEnum


class GenericFamily(StrEnum):
    LIST = "list"
    SET = "set"
    DICT = "dict"
    FROZENSET = "frozenset"
    TUPLE = "tuple"
    SEQUENCE = "Sequence"
    MAPPING = "Mapping"


@dataclass(frozen=True, slots=True)
class GenericType[T]:
    family: GenericFamily
    arguments: tuple[T, ...]
    variadic: bool = False
