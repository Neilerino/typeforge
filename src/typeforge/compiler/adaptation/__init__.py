"""Adapt authored source data into target-side stub IR."""

from typeforge.compiler.adaptation._models import (
    AdaptationError,
    SemanticRelationshipAlias,
)
from typeforge.compiler.adaptation._source_to_ir import (
    adapt_source_module,
    expand_map_aliases,
)

__all__ = [
    "AdaptationError",
    "SemanticRelationshipAlias",
    "adapt_source_module",
    "expand_map_aliases",
]
