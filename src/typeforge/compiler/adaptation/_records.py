"""Integrate discovered records and their authored origins into adaptation."""

from dataclasses import replace

from typeforge.compiler.record_materialization import (
    materialize_record_transforms,
    replace_record_aliases_in_declaration,
)
from typeforge.compiler.source import SourceModule, SourceSpan
from typeforge.compiler.stub_ir import (
    Declaration,
    FunctionDeclaration,
    GeneratedElementOrigin,
    StubModule,
    merge_imports,
)
from typeforge.utils.error_handling import ok


def materialize_records(source: SourceModule, module: StubModule) -> StubModule:
    records = ok(materialize_record_transforms(source, module))
    if not records.declarations:
        return module

    replacements = dict(records.replacements)
    declarations: list[Declaration] = list(records.declarations)
    origins: list[GeneratedElementOrigin[SourceSpan]] = []
    functions = {
        item.name: item for item in source.functions if len(item.qualified_name) == 1
    }
    for declaration in module.declarations:
        replacement = replace_record_aliases_in_declaration(
            replacements.get(declaration.name, declaration)
            if isinstance(declaration, FunctionDeclaration)
            else declaration,
            records.derived,
        )
        declarations.append(replacement)
        existing_origins = tuple(
            item for item in module.origins if item.generated is declaration
        )
        origins.extend(
            GeneratedElementOrigin(item.origin, replacement)
            for item in existing_origins
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
    origins.extend(
        GeneratedElementOrigin(aliases[derived.alias].span, generated)
        for derived, generated in zip(
            records.derived,
            records.declarations[source_record_count:],
            strict=True,
        )
    )
    declaration_order = {id(item): index for index, item in enumerate(declarations)}
    return replace(
        module,
        declarations=tuple(declarations),
        imports=merge_imports((*module.imports, *records.imports)),
        origins=tuple(
            sorted(
                origins,
                key=lambda item: (
                    item.origin.start.line,
                    item.origin.start.column,
                    declaration_order[id(item.generated)],
                ),
            )
        ),
    )
