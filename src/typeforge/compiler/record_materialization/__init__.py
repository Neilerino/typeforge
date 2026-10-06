"""Materialize authored structural records as concrete stub declarations."""

from typeforge.compiler.record_materialization._materialization import (
    build_record_shapes,
    derive_record_shapes,
    evaluate_record_application,
    is_record_alias,
    materialize_record_transforms,
    typed_dict_declaration,
)
from typeforge.compiler.record_materialization._models import (
    DerivedRecord,
    RecordMaterialization,
    RecordMaterializationError,
)
from typeforge.compiler.record_materialization._naming import available_record_name
from typeforge.compiler.record_materialization._rewriting import RecordAliasRewriter

__all__ = [
    "DerivedRecord",
    "RecordAliasRewriter",
    "RecordMaterialization",
    "RecordMaterializationError",
    "available_record_name",
    "build_record_shapes",
    "derive_record_shapes",
    "evaluate_record_application",
    "is_record_alias",
    "materialize_record_transforms",
    "typed_dict_declaration",
]
