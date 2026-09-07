"""THROWAWAY: normalize subscription slices before typing sees type parameters.

Use ``from typeforge._slice_map_prototype import Map`` for this experiment.
The resulting object uses the existing public Map/Case/Default markers, so the
Pydantic frontend and evaluator are deliberately unchanged.
"""

from types import GenericAlias
from typing import Literal, cast, get_args, get_origin

from typeforge._markers import All, Assignable, Case, Default, Equal, Not
from typeforge._markers import Any as AnyCondition
from typeforge._markers import Map as CanonicalMap


class Map:
    """Prototype construction facade; not the final public typing declaration."""

    def __class_getitem__(cls, parameters: object) -> GenericAlias:
        arguments = (
            cast(tuple[object, ...], parameters)
            if isinstance(parameters, tuple)
            else (parameters,)
        )
        if len(arguments) < 2:
            raise TypeError("Map requires a subject and at least one branch")

        subject, *entries = arguments
        normalized: list[object] = []
        for entry in entries:
            if not isinstance(entry, slice):
                normalized.append(entry)
                continue

            branch = cast("slice[object, object, object]", entry)
            if branch.step is not None:
                raise TypeError("Map branches do not accept a slice step")

            # Python erases the distinction between a missing endpoint and None.
            if branch.start is None or branch.stop is None:
                raise TypeError("Use types.NoneType for a None type in a slice branch")

            normalized.append(
                _apply(Default, (branch.stop,))
                if branch.start is Ellipsis
                else _apply(Case, (_bind_selector(branch.start, subject), branch.stop))
            )

        return _apply(CanonicalMap, (subject, *normalized))


def _bind_selector(selector: object, subject: object) -> object:
    origin = get_origin(selector)
    arguments: tuple[object, ...] = get_args(selector)
    if origin in (Equal, Assignable) and len(arguments) == 1:
        return _apply(origin, (subject, _literal(arguments[0])))

    if origin in (All, AnyCondition, Not):
        return _apply(
            origin, tuple(_bind_selector(argument, subject) for argument in arguments)
        )

    return _literal(selector)


def _literal(value: object) -> object:
    if isinstance(value, str | bytes | bool | int):
        return Literal[value]

    return value


def _apply(marker: object, arguments: tuple[object, ...]) -> GenericAlias:
    # GenericAlias accepts TypeAliasType at runtime; typeshed narrows origin to type.
    return GenericAlias(cast(type, marker), arguments)
