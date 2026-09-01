from typeforge.analysis.model import SourcePosition
from typeforge.analysis.positions import (
    source_position_from_utf8,
    source_position_from_utf16,
    utf16_character,
)


def test_utf16_positions_round_trip_non_bmp_characters() -> None:
    source = 'label = "😀"; result = 1\n'
    codepoint_column = source.index("result")
    position = SourcePosition(
        offset=codepoint_column,
        line=0,
        column=codepoint_column,
    )

    character = utf16_character(source, position)
    restored = source_position_from_utf16(source, 0, character)

    assert character == codepoint_column + 1
    assert restored == position


def test_utf16_positions_clamp_to_line_boundaries() -> None:
    source = "😀\n"

    assert source_position_from_utf16(source, 0, 1).column == 0
    assert source_position_from_utf16(source, 0, 99).column == 1


def test_utf8_byte_positions_map_to_codepoint_columns() -> None:
    source = 'label = "😀"; result = 1\n'
    codepoint_column = source.index("result")
    byte_column = len(source[:codepoint_column].encode("utf-8"))

    position = source_position_from_utf8(source, 0, byte_column)

    assert position.offset == codepoint_column
    assert position.column == codepoint_column
