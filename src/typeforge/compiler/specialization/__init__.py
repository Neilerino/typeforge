"""Finite expansion of callable relationships represented in stub IR."""

from typeforge.compiler.specialization._bounds import checker_type_bound
from typeforge.compiler.specialization._lowering import (
    lower_variadic_module,
    map_default_output,
    map_specializations,
    predicate_controller,
    predicate_is_supported,
)
from typeforge.compiler.specialization._models import (
    ArityFrontier,
    LoweringError,
    LoweringErrorCode,
)

__all__ = [
    "ArityFrontier",
    "LoweringError",
    "LoweringErrorCode",
    "checker_type_bound",
    "lower_variadic_module",
    "map_default_output",
    "map_specializations",
    "predicate_controller",
    "predicate_is_supported",
]
