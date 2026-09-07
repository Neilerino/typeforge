"""Construct canonical Map annotations before Python discovers type parameters."""

from types import GenericAlias, NoneType
from typing import Literal, TypeAliasType, cast, get_args, get_origin

from typeforge._markers import All, Assignable, Case, Default, Equal, Not
from typeforge._markers import Any as AnyCondition
from typeforge._markers import Map as CanonicalMap


class Map:
    """Inert authoring constructor; subscriptions contain canonical marker data."""

    __value__ = CanonicalMap.__value__

    def __class_getitem__(cls, parameters: object) -> GenericAlias:
        arguments = (
            cast(tuple[object, ...], parameters)
            if isinstance(parameters, tuple)
            else (parameters,)
        )
        if len(arguments) < 2:
            raise TypeError("Map requires a subject and at least one branch")

        subject, *entries = arguments
        subject = NoneType if subject is None else subject
        normalized: list[object] = []
        for entry in entries:
            if normalized and get_origin(normalized[-1]) is Default:
                raise TypeError("Map fallback must be last; no branch may follow it")

            if isinstance(entry, slice):
                branch = cast("slice[object, object, object]", entry)
                if branch.step is not None:
                    raise TypeError("Map branches do not accept a slice step")

                output = NoneType if branch.stop is None else branch.stop
                normalized.append(
                    _apply(Default, (output,))
                    if branch.start is Ellipsis
                    else _apply(
                        Case,
                        (_bind_selector(branch.start, subject), output),
                    )
                )
            elif isinstance(get_origin(entry) or entry, TypeAliasType):
                # Legacy Case/Default entries may be hidden behind aliases. Leave
                # expansion to the frontend until their removal in slice 11.
                normalized.append(entry)
            else:
                raise TypeError("Map branches must use selector: output syntax")

        return _apply(CanonicalMap, (subject, *normalized))


def _bind_selector(selector: object, subject: object) -> object:
    origin = get_origin(selector)
    arguments: tuple[object, ...] = get_args(selector)
    if origin in (Equal, Assignable) and len(arguments) == 1:
        return _apply(origin, (subject, _literal_selector(arguments[0])))

    if origin in (All, AnyCondition, Not):
        return _apply(
            origin, tuple(_bind_selector(argument, subject) for argument in arguments)
        )

    # Alias expansion and binding through aliases belong to the frontend (slice 05).
    return _literal_selector(selector)


def _literal_selector(value: object) -> object:
    if value is None:
        return NoneType

    if isinstance(value, str):
        raise TypeError('Map string selectors require Literal["text"]')

    if type(value) in (bytes, bool, int):
        return Literal[value]

    return value


def _apply(marker: object, arguments: tuple[object, ...]) -> GenericAlias:
    # Python accepts TypeAliasType origins; typeshed restricts this boundary to type.
    return GenericAlias(cast(type, marker), arguments)
