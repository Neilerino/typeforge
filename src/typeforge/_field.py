"""Construct symbolic field data without evaluating application annotations."""

from abc import abstractmethod
from enum import Enum
from types import GenericAlias
from typing import Literal, Self, get_args


class Unchanged(Enum):
    VALUE = "unchanged"


UNCHANGED = Unchanged.VALUE


class FieldValue(GenericAlias):
    """Preserve field operations when GenericAlias forwards origin attributes."""

    __slots__ = ()

    def __getattribute__(self, name: str) -> object:
        if name in {"name", "type", "replace"}:
            return object.__getattribute__(self, name)

        return super().__getattribute__(name)

    def __bool__(self) -> bool:
        raise TypeError("symbolic field truthiness is unsupported; use Map")

    @property
    @abstractmethod
    def name(self) -> object: ...

    @property
    @abstractmethod
    def type(self) -> object: ...

    def replace(
        self,
        *,
        name: object = UNCHANGED,
        type: object = UNCHANGED,
        required: bool | Unchanged = UNCHANGED,
        readonly: bool | Unchanged = UNCHANGED,
    ) -> FieldReplacementTemplate:
        return FieldReplacementTemplate.__class_getitem__(
            (self, name, type, required, readonly)
        )


class FieldTemplate(FieldValue):
    __slots__ = ()

    @classmethod
    def __class_getitem__(cls, arguments: tuple[object, ...]) -> Self:
        if len(arguments) != 4 or not all(
            isinstance(argument, bool) for argument in arguments[2:]
        ):
            raise TypeError("invalid Field template")

        name, value, required, readonly = arguments
        return super().__new__(
            cls, cls, (_name_argument(name), value, required, readonly)
        )

    @property
    def name(self) -> object:
        return get_args(self)[0]

    @property
    def type(self) -> object:
        return get_args(self)[1]


class FieldReplacementTemplate(FieldValue):
    __slots__ = ()

    @classmethod
    def __class_getitem__(cls, arguments: tuple[object, ...]) -> Self:
        if (
            len(arguments) != 5
            or not isinstance(arguments[0], FieldValue)
            or not all(
                argument is UNCHANGED or isinstance(argument, bool)
                for argument in arguments[3:]
            )
        ):
            raise TypeError("invalid field replacement template")

        original, name, value, required, readonly = arguments
        return super().__new__(
            cls, cls, (original, _name_argument(name), value, required, readonly)
        )

    @property
    def name(self) -> object:
        original, name, *_ = get_args(self)
        assert isinstance(original, FieldValue)
        return original.name if name is UNCHANGED else name

    @property
    def type(self) -> object:
        original, _, field_type, *_ = get_args(self)
        assert isinstance(original, FieldValue)
        return original.type if field_type is UNCHANGED else field_type


def Field(
    *, name: object, type: object, required: bool = True, readonly: bool = False
) -> FieldTemplate:
    """Construct a new field with explicit keyword data.

    Name and type are required. Required defaults to True and readonly to False.
    Use a scoped field.replace operation when preserving an existing field's
    unedited properties rather than creating a new entry.

    ```python
    @type_function
    def Renamed[T]():
        return Record(
            Field(name="display_name", type=field.type, required=False)
            for field in Fields[T]
        )
    ```
    """
    return FieldTemplate.__class_getitem__((name, type, required, readonly))


def _name_argument(value: object) -> object:
    # Generic typing reconstruction otherwise resolves names as forward references.
    return Literal[value] if isinstance(value, str) else value
