"""Materialize authored structural records as concrete stub declarations."""

from typeforge.compiler.record_materialization._materialization import (
    build_record_shapes,
    derive_record_shapes,
    is_record_alias,
    materialize_record_transforms,
)
from typeforge.compiler.record_materialization._models import (
    DerivedRecord,
    RecordMaterialization,
    RecordMaterializationError,
)
from typeforge.compiler.record_materialization._rewriting import RecordAliasRewriter

__all__ = [
    "DerivedRecord",
    "RecordAliasRewriter",
    "RecordMaterialization",
    "RecordMaterializationError",
    "build_record_shapes",
    "derive_record_shapes",
    "is_record_alias",
    "materialize_record_transforms",
]
