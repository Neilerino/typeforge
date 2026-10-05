from typing import TYPE_CHECKING

from typeforge._capture import Capture
from typeforge._documentation import Doc
from typeforge._markers import (
    Collect,
    Drop,
    Each,
    Field,
    Is,
    Map,
    OptionalField,
    ReadonlyField,
)
from typeforge._record import Fields, Record
from typeforge._type_function import TypeFunctionConstructionError, type_function

if not TYPE_CHECKING:
    # Checkers retain the inert object alias; runtime subscriptions normalize slices.
    from typeforge._map import Map

__all__ = [
    "Capture",
    "Collect",
    "Doc",
    "Drop",
    "Each",
    "Field",
    "Fields",
    "Is",
    "Map",
    "OptionalField",
    "ReadonlyField",
    "Record",
    "TypeFunctionConstructionError",
    "type_function",
]
