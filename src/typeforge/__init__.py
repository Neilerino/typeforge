from typing import TYPE_CHECKING

from typeforge._documentation import Doc
from typeforge._markers import (
    All,
    Any,
    Assignable,
    Collect,
    Drop,
    Each,
    Equal,
    Field,
    Key,
    Map,
    MapFields,
    Not,
    OptionalField,
    ReadonlyField,
    Value,
)

if not TYPE_CHECKING:
    # Checkers retain the inert object alias; runtime subscriptions normalize slices.
    from typeforge._map import Map

__all__ = [
    "All",
    "Any",
    "Assignable",
    "Collect",
    "Doc",
    "Drop",
    "Each",
    "Equal",
    "Field",
    "Key",
    "Map",
    "MapFields",
    "Not",
    "OptionalField",
    "ReadonlyField",
    "Value",
]
