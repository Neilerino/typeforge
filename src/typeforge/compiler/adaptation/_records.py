"""Integrate discovered records and their authored origins into adaptation."""

from dataclasses import replace

from typeforge.compiler.adaptation._context import class_type_environment
from typeforge.compiler.adaptation._record_applications import (
    materialize_record_applications,
)
from typeforge.compiler.adaptation._schema_aliases import expand_schema_aliases
from typeforge.compiler.record_materialization import (
    RecordAliasRewriter,
    RecordMaterialization,
    materialize_record_transforms,
    typed_dict_declaration,
)
from typeforge.compiler.source import (
    FieldReferenceTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    SourceModule,
    SourceSpan,
    SourceTypeExpression,
    TypedDictDeclaration,
    TypedDictField,
    opaque_enriched_annotations,
    walk_type_expression,
)
from typeforge.compiler.source import TypeAliasDeclaration as SourceTypeAlias
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    Declaration,
    FunctionDeclaration,
    GeneratedElement,
    GeneratedElementOrigin,
    StubModule,
    StubTypeExpression,
    is_declaration,
    merge_imports,
    walk_declaration,
    walk_module,
)


def materialize_records(source: SourceModule, module: StubModule) -> StubModule:
    source = _expand_record_aliases(source)
    origins = _RecordOrigins(module.origins)

    records = materialize_record_transforms(
        source,
        module,
        on_rewrite=origins.record_rewrite,
        environment=class_type_environment(source),
    ).unwrap()
    applications = materialize_record_applications(source, module, records)
    application_declarations = tuple(
        (typed_dict_declaration(shape), span) for shape, span in applications.shapes
    )

    if not records.declarations:
        return module

    rewriter = RecordAliasRewriter(
        records.derived,
        on_rewrite=origins.record_rewrite,
        applications=applications.replacements,
    )
    declarations, declaration_origins = _rewrite_declarations(
        source, module, records, rewriter
    )
    reusable_elements = _rewrite_reusable_elements(source, module, rewriter)
    materialized = replace(
        module,
        declarations=(
            *records.declarations,
            *(declaration for declaration, _ in application_declarations),
            *declarations,
        ),
        reusable_elements=reusable_elements,
        imports=merge_imports((*module.imports, *records.imports)),
    )
    additional_origins = (
        *declaration_origins,
        *_record_origins(source, records),
        *(
            GeneratedElementOrigin(span, element)
            for declaration, span in application_declarations
            for element in walk_declaration(declaration)
        ),
    )
    current_origins = origins.for_module(materialized, additional_origins)
    return replace(materialized, origins=current_origins)


def _expand_record_aliases(source: SourceModule) -> SourceModule:
    aliases: list[SourceTypeAlias] = []
    for alias in source.aliases:
        value = expand_schema_aliases(
            alias.value,
            source.aliases,
            declaration=alias.name,
            predicates_only=True,
        ).unwrap()
        aliases.append(replace(alias, value=value))

    if not any(_selects_field_type(alias.value) for alias in aliases):
        return replace(source, aliases=tuple(aliases))

    records: list[TypedDictDeclaration] = []
    for declaration in source.typed_dicts:
        fields: list[TypedDictField] = []
        for field in declaration.fields:
            annotation = expand_schema_aliases(
                opaque_enriched_annotations(field.annotation),
                source.aliases,
                declaration=declaration.name,
            ).unwrap()
            fields.append(replace(field, annotation=annotation))

        records.append(replace(declaration, fields=tuple(fields)))

    return replace(source, aliases=tuple(aliases), typed_dicts=tuple(records))


def _selects_field_type(expression: SourceTypeExpression) -> bool:
    """Ordinary passthrough needs no recursive alias-selection capability."""
    for item in walk_type_expression(expression):
        if not (
            isinstance(item, MarkerTypeExpression)
            and item.marker is MarkerKind.MAP
            and item.arguments
        ):
            continue

        subject, *entries = item.arguments
        selectors = (
            entry.arguments[0]
            for entry in entries
            if isinstance(entry, MarkerTypeExpression)
            and entry.marker is MarkerKind.CASE
            and entry.arguments
        )
        for operand in (subject, *selectors):
            if any(
                isinstance(child, FieldReferenceTypeExpression)
                and child.attribute == "type"
                for child in walk_type_expression(operand)
            ):
                return True

    return False


def _rewrite_declarations(
    source: SourceModule,
    module: StubModule,
    records: RecordMaterialization,
    rewriter: RecordAliasRewriter,
) -> tuple[tuple[Declaration, ...], tuple[GeneratedElementOrigin[SourceSpan], ...]]:
    """Apply record replacements without confusing module and scoped functions."""
    replacements = dict(records.replacements)
    declarations: list[Declaration] = []
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
        replacement = declaration
        if (
            isinstance(declaration, FunctionDeclaration)
            and id(declaration) not in scoped_functions
        ):
            replacement = replacements.get(declaration.name, declaration)

        replacement = rewriter.rewrite_declaration(replacement)
        declarations.append(replacement)
        rewritten_origins = _rewritten_declaration_origins(
            module.origins, declaration, replacement
        )
        origins.extend(rewritten_origins)

        if (
            isinstance(declaration, FunctionDeclaration)
            and declaration.name in replacements
            and not rewritten_origins
        ):
            origins.append(
                GeneratedElementOrigin(functions[declaration.name].span, replacement)
            )

    return tuple(declarations), tuple(origins)


def _rewritten_declaration_origins(
    origins: tuple[GeneratedElementOrigin[SourceSpan], ...],
    original: Declaration,
    replacement: Declaration,
) -> tuple[GeneratedElementOrigin[SourceSpan], ...]:
    rewritten = tuple(
        replace(item, generated=replacement)
        for item in origins
        if item.generated is original
    )
    if isinstance(original, ClassDeclaration) and isinstance(
        replacement, ClassDeclaration
    ):
        for original_method, replacement_method in zip(
            original.methods, replacement.methods, strict=True
        ):
            method_origins = tuple(
                replace(item, generated=replacement_method)
                for item in origins
                if item.generated is original_method
            )
            rewritten += method_origins

    return rewritten


def _record_origins(
    source: SourceModule, records: RecordMaterialization
) -> tuple[GeneratedElementOrigin[SourceSpan], ...]:
    """Associate each derived record with both its transform and input record."""
    source_record_count = len(source.typed_dicts)
    source_declarations = records.declarations[:source_record_count]
    derived_declarations = records.declarations[source_record_count:]
    origins = [
        GeneratedElementOrigin(authored.span, generated)
        for authored, generated in zip(
            source.typed_dicts, source_declarations, strict=True
        )
    ]
    aliases = {item.name: item for item in source.aliases}
    source_records = {item.name: item for item in source.typed_dicts}
    for derived, generated in zip(records.derived, derived_declarations, strict=True):
        alias = aliases[derived.alias]
        input_record = source_records[derived.input_name]
        origins.append(GeneratedElementOrigin(alias.span, generated))
        origins.append(GeneratedElementOrigin(input_record.span, generated))

    return tuple(origins)


def _rewrite_reusable_elements(
    source: SourceModule,
    module: StubModule,
    rewriter: RecordAliasRewriter,
) -> tuple[GeneratedElement, ...]:
    """Rewrite expression roots while retaining authored aliases and contracts."""
    alias_spans = {alias.span for alias in source.aliases}
    alias_roots = {
        id(origin.generated)
        for origin in module.origins
        if origin.origin in alias_spans
    }
    rewritten: list[GeneratedElement] = []
    for element in module.reusable_elements:
        if is_declaration(element) or id(element) in alias_roots:
            rewritten.append(element)
        else:
            replacement = rewriter.rewrite_type(element)
            rewritten.append(replacement)

    return tuple(rewritten)


class _RecordOrigins:
    """Track expression rewrites during one record-materialization operation."""

    def __init__(self, origins: tuple[GeneratedElementOrigin[SourceSpan], ...]) -> None:
        self._origins = list(origins)

    def record_rewrite(
        self, original: StubTypeExpression, replacement: StubTypeExpression
    ) -> None:
        if original is replacement:
            return

        rewritten = tuple(
            replace(item, generated=replacement)
            for item in self._origins
            if item.generated is original
        )
        self._origins.extend(rewritten)

    def for_module(
        self,
        module: StubModule,
        additional_origins: tuple[GeneratedElementOrigin[SourceSpan], ...],
    ) -> tuple[GeneratedElementOrigin[SourceSpan], ...]:
        """Retain reachable origins, deduplicated and ordered deterministically."""
        declaration_order: dict[int, int] = {}
        for element in walk_module(module):
            declaration_order.setdefault(id(element), len(declaration_order))

        origins = (*additional_origins, *self._origins)
        unique_origins = {
            (item.origin, id(item.generated)): item
            for item in origins
            if id(item.generated) in declaration_order
        }
        ordered_origins = sorted(
            unique_origins.values(),
            key=lambda item: (
                item.origin.start.line,
                item.origin.start.column,
                declaration_order[id(item.generated)],
            ),
        )
        return tuple(ordered_origins)
