from typing import TYPE_CHECKING

from typeforge._capture import Capture
from typeforge._documentation import Doc
from typeforge._markers import (
    Collect,
    Drop,
    Each,
    Field,
    Is,
    Key,
    Map,
    MapFields,
    OptionalField,
    ReadonlyField,
    Value,
)
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
    "Is",
    "Key",
    "Map",
    "MapFields",
    "OptionalField",
    "ReadonlyField",
    "TypeFunctionConstructionError",
    "Value",
    "type_function",
]
