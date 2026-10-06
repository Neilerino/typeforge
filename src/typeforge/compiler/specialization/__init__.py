"""Finite expansion of callable relationships represented in stub IR."""

from typeforge.compiler.specialization._bounds import checker_type_bound
from typeforge.compiler.specialization._coverage import (
    map_case_input,
    map_default_reachable,
)
from typeforge.compiler.specialization._evaluation import instantiate_output
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
    "instantiate_output",
    "lower_variadic_module",
    "map_case_input",
    "map_default_output",
    "map_default_reachable",
    "map_specializations",
    "predicate_controller",
    "predicate_is_supported",
]
