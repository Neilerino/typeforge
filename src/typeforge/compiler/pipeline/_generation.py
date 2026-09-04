"""Compose compiler stages into generated modules."""

from pathlib import Path

from returns.result import Result

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.emission import EmissionError, emit_stub_module
from typeforge.compiler.module_surface import ModuleSurface, inspect_module_surface
from typeforge.compiler.pipeline._models import GeneratedModule, GenerationError
from typeforge.compiler.record_materialization import (
    RecordMaterialization,
    apply_record_materialization,
    materialize_record_transforms,
)
from typeforge.compiler.source import parse_module
from typeforge.compiler.specialization import ArityFrontier, lower_variadic_module
from typeforge.compiler.stub_ir import StubModule, merge_imports


def generate_module(
    path: Path,
    maximum_arity: int,
) -> Result[GeneratedModule, GenerationError]:
    return Result.do(
        generated
        for parsed in parse_module(path)
        for surface in inspect_module_surface(parsed)
        for adapted in adapt_source_module(parsed)
        for records in materialize_record_transforms(parsed, adapted)
        for lowered in lower_variadic_module(
            apply_record_materialization(adapted, records),
            ArityFrontier(0, maximum_arity),
        )
        for generated in _emit_generated_module(path, lowered, records, surface)
    )


def _emit_generated_module(
    path: Path,
    lowered: StubModule,
    records: RecordMaterialization,
    surface: ModuleSurface,
) -> Result[GeneratedModule, EmissionError]:
    generated = StubModule(
        lowered.name,
        (*records.declarations, *surface.declarations, *lowered.declarations),
        merge_imports((*lowered.imports, *surface.imports)),
    )
    return emit_stub_module(generated).map(
        lambda emitted: GeneratedModule(path, emitted)
    )
