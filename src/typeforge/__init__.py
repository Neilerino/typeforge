from typing import TYPE_CHECKING

from typeforge._documentation import Doc
from typeforge._markers import (
    All,
    Any,
    Assignable,
    Case,
    Collect,
    Default,
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
    "Case",
    "Collect",
    "Default",
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
