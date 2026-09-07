"""Materialize authored structural records as concrete stub declarations."""

from typeforge.compiler.record_materialization._materialization import (
    build_record_shapes,
    derive_record_shapes,
    is_map_fields_alias,
    materialize_record_transforms,
    replace_record_aliases,
    replace_record_aliases_in_declaration,
)
from typeforge.compiler.record_materialization._models import (
    DerivedRecord,
    RecordMaterialization,
    RecordMaterializationError,
)

__all__ = [
    "DerivedRecord",
    "RecordMaterialization",
    "RecordMaterializationError",
    "build_record_shapes",
    "derive_record_shapes",
    "is_map_fields_alias",
    "materialize_record_transforms",
    "replace_record_aliases",
    "replace_record_aliases_in_declaration",
]
