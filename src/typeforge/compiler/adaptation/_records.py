"""Integrate discovered records and their authored origins into adaptation."""

from dataclasses import replace

from typeforge.compiler.record_materialization import (
    materialize_record_transforms,
    replace_record_aliases,
    replace_record_aliases_in_declaration,
)
from typeforge.compiler.source import SourceModule, SourceSpan
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    Declaration,
    FunctionDeclaration,
    GeneratedElementOrigin,
    StubModule,
    StubTypeExpression,
    is_declaration,
    merge_imports,
    walk_module,
)
from typeforge.utils.error_handling import ok


def materialize_records(source: SourceModule, module: StubModule) -> StubModule:
    expression_origins = list(module.origins)

    def record_rewrite(
        original: StubTypeExpression, replacement: StubTypeExpression
    ) -> None:
        if original is not replacement:
            expression_origins.extend(
                replace(item, generated=replacement)
                for item in tuple(expression_origins)
                if item.generated is original
            )

    records = ok(
        materialize_record_transforms(source, module, on_rewrite=record_rewrite)
    )
    if not records.declarations:
        return module

    replacements = dict(records.replacements)
    declarations: list[Declaration] = list(records.declarations)
    origins: list[GeneratedElementOrigin[SourceSpan]] = []
    functions = {
        item.name: item for item in source.functions if len(item.qualified_name) == 1
    }
    scoped_spans = {
        function.span
        for function in source.functions
        if len(function.qualified_name) > 1
    }
    scoped_functions = {
        id(origin.generated)
        for origin in module.origins
        if origin.origin in scoped_spans
    }
    for declaration in module.declarations:
        replacement = replace_record_aliases_in_declaration(
            replacements.get(declaration.name, declaration)
            if isinstance(declaration, FunctionDeclaration)
            and id(declaration) not in scoped_functions
            else declaration,
            records.derived,
            on_rewrite=record_rewrite,
        )
        declarations.append(replacement)
        existing_origins = tuple(
            item for item in module.origins if item.generated is declaration
        )
        origins.extend(
            GeneratedElementOrigin(item.origin, replacement)
            for item in existing_origins
        )
        if isinstance(declaration, ClassDeclaration) and isinstance(
            replacement, ClassDeclaration
        ):
            for original_method, replacement_method in zip(
                declaration.methods, replacement.methods, strict=True
            ):
                origins.extend(
                    GeneratedElementOrigin(item.origin, replacement_method)
                    for item in module.origins
                    if item.generated is original_method
                )

        if (
            isinstance(declaration, FunctionDeclaration)
            and declaration.name in replacements
            and not existing_origins
        ):
            origins.append(
                GeneratedElementOrigin(functions[declaration.name].span, replacement)
            )

    source_record_count = len(source.typed_dicts)
    origins.extend(
        GeneratedElementOrigin(authored.span, generated)
        for authored, generated in zip(
            source.typed_dicts,
            records.declarations[:source_record_count],
            strict=True,
        )
    )
    aliases = {item.name: item for item in source.aliases}
    source_records = {item.name: item for item in source.typed_dicts}
    origins.extend(
        GeneratedElementOrigin(authored.span, generated)
        for derived, generated in zip(
            records.derived,
            records.declarations[source_record_count:],
            strict=True,
        )
        for authored in (aliases[derived.alias], source_records[derived.input_name])
    )
    alias_spans = {alias.span for alias in source.aliases}
    alias_roots = {
        id(origin.generated)
        for origin in module.origins
        if origin.origin in alias_spans
    }
    reusable_elements = tuple(
        element
        if is_declaration(element) or id(element) in alias_roots
        else replace_record_aliases(element, records.derived, on_rewrite=record_rewrite)
        for element in module.reusable_elements
    )
    materialized = replace(
        module,
        declarations=tuple(declarations),
        reusable_elements=reusable_elements,
        imports=merge_imports((*module.imports, *records.imports)),
    )
    declaration_order: dict[int, int] = {}
    for element in walk_module(materialized):
        declaration_order.setdefault(id(element), len(declaration_order))

    return replace(
        materialized,
        origins=tuple(
            sorted(
                {
                    (item.origin, id(item.generated)): item
                    for item in (*origins, *expression_origins)
                    if id(item.generated) in declaration_order
                }.values(),
                key=lambda item: (
                    item.origin.start.line,
                    item.origin.start.column,
                    declaration_order[id(item.generated)],
                ),
            )
        ),
    )
