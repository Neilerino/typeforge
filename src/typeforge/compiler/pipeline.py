"""Public compiler pipeline API.

Implementation details live in internal modules so consumers depend on a small,
deliberate surface instead of the pipeline's orchestration helpers.
"""

from pathlib import Path

from returns.result import Result

from typeforge.compiler._pipeline_adaptation import (
    adapt_alias,
    adapt_function,
    adapt_source_module,
    adapt_type_expression,
    collect_semantic_relationship_aliases,
    expand_function_map_aliases,
    expand_map_aliases,
    substitute_type,
)
from typeforge.compiler._pipeline_models import (
    AdaptationError,
    DerivedRecord,
    EmissionError,
    GeneratedModule,
    GenerationError,
    RecordMaterialization,
    SemanticRelationshipAlias,
    UnsupportedPublicDeclaration,
)
from typeforge.compiler._pipeline_records import (
    apply_record_materialization,
    build_record_shapes,
    derive_record_shapes,
    materialize_record_transforms,
    render_typed_dict,
    replace_record_aliases,
)
from typeforge.compiler._pipeline_utils import (
    collect_module_variables,
    merge_imports,
    validate_public_surface,
)
from typeforge.compiler.emitter import emit_stub_module
from typeforge.compiler.frontend import parse_module
from typeforge.compiler.lowering import (
    ArityFrontier,
    StubModule,
    lower_variadic_module,
)
from typeforge.compiler.model import SourceModule


def generate_module(
    path: Path,
    maximum_arity: int,
) -> Result[GeneratedModule, GenerationError]:
    return Result.do(
        generated
        for parsed in parse_module(path)
        for _ in validate_public_surface(parsed)
        for adapted in adapt_source_module(parsed)
        for records in materialize_record_transforms(parsed, adapted)
        for lowered in lower_variadic_module(
            apply_record_materialization(adapted, records),
            ArityFrontier(0, maximum_arity),
        )
        for generated in _emit_generated_module(path, parsed, lowered, records)
    )


def _emit_generated_module(
    path: Path,
    parsed: SourceModule,
    lowered: StubModule,
    records: RecordMaterialization,
) -> Result[GeneratedModule, EmissionError]:
    variables = collect_module_variables(parsed.path)
    generated = StubModule(
        lowered.name,
        (*records.declarations, *variables.declarations, *lowered.declarations),
        merge_imports((*lowered.imports, *variables.imports)),
    )
    return (
        emit_stub_module(generated)
        .alt(EmissionError)
        .map(lambda emitted: GeneratedModule(path, emitted))
    )


__all__ = (
    "AdaptationError",
    "DerivedRecord",
    "EmissionError",
    "GeneratedModule",
    "GenerationError",
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
)
