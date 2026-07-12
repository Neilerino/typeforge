from typeforge.analysis.model import SourcePosition


def source_position_from_utf16(
    source: str, line: int, character: int
) -> SourcePosition:
    lines = source.splitlines(keepends=True)
    bounded_line = min(max(line, 0), len(lines))
    offset = sum(len(item) for item in lines[:bounded_line])
    column = 0
    if bounded_line < len(lines):
        text = lines[bounded_line].rstrip("\r\n")
        column = codepoint_column_from_utf16(text, character)
        offset += column
    return SourcePosition(offset=offset, line=bounded_line, column=column)


def source_position_from_utf8(source: str, line: int, character: int) -> SourcePosition:
    lines = source.splitlines(keepends=True)
    bounded_line = min(max(line, 0), len(lines))
    offset = sum(len(item) for item in lines[:bounded_line])
    column = 0
    if bounded_line < len(lines):
        text = lines[bounded_line].rstrip("\r\n")
        encoded = text.encode("utf-8")
        bounded_character = min(max(character, 0), len(encoded))
        column = len(encoded[:bounded_character].decode("utf-8", errors="ignore"))
        offset += column
    return SourcePosition(offset=offset, line=bounded_line, column=column)


def utf16_character(source: str, position: SourcePosition) -> int:
    lines = source.splitlines(keepends=True)
    if position.line < 0 or position.line >= len(lines):
        return max(position.column, 0)
    text = lines[position.line].rstrip("\r\n")
    column = min(max(position.column, 0), len(text))
    return len(text[:column].encode("utf-16-le")) // 2


def codepoint_column_from_utf16(text: str, character: int) -> int:
    target = max(character, 0)
    units = 0
    for column, value in enumerate(text):
        next_units = units + (2 if ord(value) > 0xFFFF else 1)
        if next_units > target:
            return column
        units = next_units
    return len(text)
