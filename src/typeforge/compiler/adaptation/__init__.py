"""Adapt authored source data into target-side stub IR."""

from typeforge.compiler.adaptation._models import (
    AdaptationError,
    SemanticRelationshipAlias,
)
from typeforge.compiler.adaptation._source_to_ir import (
    adapt_alias,
    adapt_function,
    adapt_source_module,
    adapt_type_expression,
    collect_semantic_relationship_aliases,
    expand_function_map_aliases,
    expand_map_aliases,
)

__all__ = [
    "AdaptationError",
    "SemanticRelationshipAlias",
    "adapt_alias",
    "adapt_function",
    "adapt_source_module",
    "adapt_type_expression",
    "collect_semantic_relationship_aliases",
    "expand_function_map_aliases",
    "expand_map_aliases",
]
