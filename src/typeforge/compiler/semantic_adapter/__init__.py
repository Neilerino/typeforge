"""Adapt compiler source types to the shared semantic engine."""

from typeforge.compiler.semantic_adapter._emission import static_type_expression
from typeforge.compiler.semantic_adapter._lowering import (
    SemanticEnvironment,
    SemanticLoweringError,
    lower_capture_reference,
    lower_semantic_expression,
)
from typeforge.compiler.semantic_adapter._type_system import (
    COMPILER_TYPE_SYSTEM,
    CompilerTypeSystem,
)
from typeforge.compiler.semantic_adapter._types import (
    NEVER,
    NamedType,
    NeverType,
    ParameterizedType,
    StaticType,
    UnionType,
    UnpackedType,
    VariadicType,
    is_static,
    union_of,
)

__all__ = [
    "COMPILER_TYPE_SYSTEM",
    "NEVER",
    "CompilerTypeSystem",
    "NamedType",
    "NeverType",
    "ParameterizedType",
    "SemanticEnvironment",
    "SemanticLoweringError",
    "StaticType",
    "UnionType",
    "UnpackedType",
    "VariadicType",
    "is_static",
    "lower_capture_reference",
    "lower_semantic_expression",
    "static_type_expression",
    "union_of",
]
