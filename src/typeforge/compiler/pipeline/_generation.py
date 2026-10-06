"""Compose compiler stages into generated modules."""

from dataclasses import replace
from pathlib import Path

from returns.result import Result

from typeforge.compiler.adaptation._imports import annotation_imports
from typeforge.compiler.emission import EmissionError, emit_stub_module
from typeforge.compiler.module_surface import ModuleSurface, inspect_module_surface
from typeforge.compiler.pipeline._compilation import compile_module
from typeforge.compiler.pipeline._models import (
    CompilationPlan,
    GeneratedModule,
    GenerationError,
)
from typeforge.compiler.source import (
    SourceModule,
    opaque_enriched_annotations,
    parse_module,
)
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
        for plan in compile_module(
            replace(parsed, source=_published_source_scope(parsed.source)),
            maximum_arity=maximum_arity,
        )
        for generated in _emit_generated_module(
            plan,
            replace(
                surface,
                imports=merge_imports(
                    (*surface.imports, *annotation_imports(parsed.source))
                ),
            ),
        )
    )


def _published_source_scope(source: SourceModule) -> SourceModule:
    # Private nested classes and main guards have historically been accepted but
    # omitted from published interfaces, including their callable failures.
    class_method_spans = {
        method.span
        for source_class in source.classes
        for method in source_class.methods
    }
    return replace(
        source,
        # Variable annotations are retained for overlay edits. Publication keeps
        # their existing module-surface policy and does not inspect local bodies.
        variable_annotations=(),
        functions=tuple(
            function
            for function in source.functions
            if len(function.qualified_name) == 1 or function.span in class_method_spans
        ),
        # Keep native typing structure for record transforms. Schema replacements
        # remain opaque and retain their separate publication policy.
        typed_dicts=tuple(
            replace(
                record,
                fields=tuple(
                    replace(
                        field,
                        annotation=opaque_enriched_annotations(field.annotation),
                    )
                    for field in record.fields
                ),
            )
            for record in source.typed_dicts
        ),
    )


def _emit_generated_module(
    plan: CompilationPlan,
    surface: ModuleSurface,
) -> Result[GeneratedModule, EmissionError]:
    lowered = plan.module
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
        lambda emitted: GeneratedModule(plan.source.path, emitted)
    )


def _is_record(declaration: Declaration) -> bool:
    return isinstance(declaration, ClassDeclaration) and (
        TypeName("tf_typing.TypedDict") in declaration.bases
    )


def _project_published_declaration(declaration: Declaration) -> Declaration:
    if isinstance(declaration, TypeAliasDeclaration) and isinstance(
        declaration.value, MapType
    ):
        return replace(declaration, value=TypeName("object"))

    return declaration
