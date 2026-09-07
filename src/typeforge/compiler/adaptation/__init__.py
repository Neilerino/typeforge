"""Adapt authored source data into target-side stub IR."""

from typeforge.compiler.adaptation._models import (
    AdaptationError,
)
from typeforge.compiler.adaptation._schema import adapt_schema_expression
from typeforge.compiler.adaptation._schema_aliases import expand_schema_aliases
from typeforge.compiler.adaptation._source_to_ir import (
    adapt_source_module,
)

__all__ = [
    "AdaptationError",
    "adapt_schema_expression",
    "adapt_source_module",
    "expand_schema_aliases",
]
