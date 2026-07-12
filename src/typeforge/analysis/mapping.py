from typeforge.analysis.model import (
    MappingKind,
    SourceMapping,
    SourcePosition,
    SourceSpan,
    VirtualDocument,
)


def authored_to_generated(
    document: VirtualDocument, position: SourcePosition
) -> SourcePosition:
    mapping = mapping_for_authored_offset(document.mappings, position.offset)
    if mapping is None:
        return position_from_offset(document.generated_text, position.offset)
    relative = position.offset - mapping.authored.start.offset
    generated_offset = min(
        mapping.generated.start.offset + max(relative, 0),
        mapping.generated.end.offset,
    )
    return position_from_offset(document.generated_text, generated_offset)


def generated_span_to_authored(
    document: VirtualDocument, span: SourceSpan
) -> SourceSpan:
    return SourceSpan(
        generated_to_authored(document, span.start),
        generated_to_authored(document, span.end),
    )


def generated_to_authored(
    document: VirtualDocument, position: SourcePosition
) -> SourcePosition:
    mapping = mapping_for_generated_offset(document.mappings, position.offset)
    if mapping is None:
        return position_from_offset(document.authored_text, position.offset)
    if mapping.origin is MappingKind.GENERATED:
        return mapping.authored.start
    relative = position.offset - mapping.generated.start.offset
    authored_offset = min(
        mapping.authored.start.offset + max(relative, 0),
        mapping.authored.end.offset,
    )
    return position_from_offset(document.authored_text, authored_offset)


def mapping_for_authored_offset(
    mappings: tuple[SourceMapping, ...], offset: int
) -> SourceMapping | None:
    authored = tuple(
        mapping for mapping in mappings if mapping.origin is MappingKind.AUTHORED
    )
    found = next(
        (
            mapping
            for mapping in authored
            if mapping.authored.start.offset <= offset < mapping.authored.end.offset
        ),
        None,
    )
    if found is not None:
        return found
    return next(
        (
            mapping
            for mapping in reversed(authored)
            if offset == mapping.authored.end.offset
        ),
        None,
    )


def mapping_for_generated_offset(
    mappings: tuple[SourceMapping, ...], offset: int
) -> SourceMapping | None:
    found = next(
        (
            mapping
            for mapping in mappings
            if mapping.generated.start.offset <= offset < mapping.generated.end.offset
        ),
        None,
    )
    if found is not None:
        return found
    return next(
        (
            mapping
            for mapping in reversed(mappings)
            if offset == mapping.generated.end.offset
        ),
        None,
    )


def position_from_offset(source: str, offset: int) -> SourcePosition:
    bounded = min(max(offset, 0), len(source))
    prefix = source[:bounded]
    line = prefix.count("\n")
    last_newline = prefix.rfind("\n")
    column = bounded if last_newline < 0 else bounded - last_newline - 1
    return SourcePosition(offset=bounded, line=line, column=column)
