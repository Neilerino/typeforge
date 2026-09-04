"""Materialize authored structural records as concrete stub declarations."""

from typeforge.compiler.record_materialization._materialization import (
    apply_record_materialization,
    build_record_shapes,
    derive_record_shapes,
    materialize_record_transforms,
    render_typed_dict,
    replace_record_aliases,
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
    "apply_record_materialization",
    "build_record_shapes",
    "derive_record_shapes",
    "materialize_record_transforms",
    "render_typed_dict",
    "replace_record_aliases",
]
