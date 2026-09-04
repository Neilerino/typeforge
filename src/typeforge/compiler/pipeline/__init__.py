"""Public compiler generation interface and compatibility exports."""

from typeforge.compiler.adaptation import (
    AdaptationError,
    SemanticRelationshipAlias,
    adapt_alias,
    adapt_function,
    adapt_type_expression,
    collect_semantic_relationship_aliases,
    expand_function_map_aliases,
    expand_map_aliases,
)
from typeforge.compiler.emission import EmissionError
from typeforge.compiler.module_surface import UnsupportedPublicDeclaration
from typeforge.compiler.pipeline._generation import generate_module
from typeforge.compiler.pipeline._models import GeneratedModule, GenerationError
from typeforge.compiler.record_materialization import (
    DerivedRecord,
    RecordMaterializationError,
    build_record_shapes,
    derive_record_shapes,
    render_typed_dict,
    replace_record_aliases,
)
from typeforge.compiler.stub_ir import substitute_type

__all__ = [
    "AdaptationError",
    "DerivedRecord",
    "EmissionError",
    "GeneratedModule",
    "GenerationError",
    "RecordMaterializationError",
    "SemanticRelationshipAlias",
    "UnsupportedPublicDeclaration",
    "adapt_alias",
    "adapt_function",
    "adapt_type_expression",
    "build_record_shapes",
    "collect_semantic_relationship_aliases",
    "derive_record_shapes",
    "expand_function_map_aliases",
    "expand_map_aliases",
    "generate_module",
    "render_typed_dict",
    "replace_record_aliases",
    "substitute_type",
]
