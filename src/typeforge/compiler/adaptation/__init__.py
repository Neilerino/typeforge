"""Adapt authored source data into target-side stub IR."""

from typeforge.compiler.adaptation._models import (
    AdaptationError,
)
from typeforge.compiler.adaptation._source_to_ir import (
    adapt_source_module,
)

__all__ = [
    "AdaptationError",
    "adapt_source_module",
]
