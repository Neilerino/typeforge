"""Compose compiler stages into generated modules."""

from pathlib import Path

from returns.result import Result

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.emission import EmissionError, emit_stub_module
from typeforge.compiler.module_surface import ModuleSurface, inspect_module_surface
from typeforge.compiler.pipeline._models import GeneratedModule, GenerationError
from typeforge.compiler.source import parse_module
from typeforge.compiler.specialization import ArityFrontier, lower_variadic_module
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    Declaration,
    MapType,
    StubModule,
    TypeAliasDeclaration,
    TypeName,
    merge_imports,
)


def generate_module(
    path: Path,
    maximum_arity: int,
) -> Result[GeneratedModule, GenerationError]:
    return Result.do(
        generated
        for parsed in parse_module(path)
        for surface in inspect_module_surface(parsed)
        for adapted in adapt_source_module(parsed)
        for lowered in lower_variadic_module(
            adapted,
            ArityFrontier(0, maximum_arity),
        )
        for generated in _emit_generated_module(
            path=path, lowered=lowered, surface=surface
        )
    )


def _emit_generated_module(
    path: Path,
    lowered: StubModule,
    surface: ModuleSurface,
) -> Result[GeneratedModule, EmissionError]:
    generated = StubModule(
        name=lowered.name,
        declarations=(
            *(item for item in lowered.declarations if _is_record(item)),
            *surface.declarations,
            *(
                _project_published_declaration(item)
                for item in lowered.declarations
                if not _is_record(item)
            ),
        ),
        imports=merge_imports((*lowered.imports, *surface.imports)),
    )
    return emit_stub_module(generated).map(
        lambda emitted: GeneratedModule(path, emitted)
    )


def _is_record(declaration: Declaration) -> bool:
    return isinstance(declaration, ClassDeclaration) and (
        TypeName("tf_typing.TypedDict") in declaration.bases
    )


def _project_published_declaration(declaration: Declaration) -> Declaration:
    if isinstance(declaration, TypeAliasDeclaration) and isinstance(
        declaration.value, MapType
    ):
        return TypeAliasDeclaration(
            declaration.name,
            TypeName("object"),
            declaration.type_parameters,
        )

    return declaration
