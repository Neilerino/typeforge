from dataclasses import dataclass

from typeforge.analysis.mapping import (
    generated_to_authored,
    mapping_for_generated_offset,
)
from typeforge.analysis.model import MappingKind, VirtualDocument
from typeforge.analysis.positions import source_position_from_utf16, utf16_character


@dataclass(frozen=True, slots=True, order=True)
class SemanticToken:
    line: int
    character: int
    length: int
    token_type: int
    modifiers: int


def map_semantic_tokens(data: list[int], document: VirtualDocument) -> list[int]:
    mapped: list[SemanticToken] = []
    for token in decode_tokens(data):
        generated = source_position_from_utf16(
            document.generated_text,
            token.line,
            token.character,
        )
        mapping = mapping_for_generated_offset(document.mappings, generated.offset)
        if mapping is None or mapping.origin is MappingKind.GENERATED:
            continue
        generated_end = source_position_from_utf16(
            document.generated_text,
            token.line,
            token.character + token.length,
        )
        authored = generated_to_authored(document, generated)
        authored_end = generated_to_authored(document, generated_end)
        if authored.line != authored_end.line:
            continue
        length = utf16_character(
            document.authored_text, authored_end
        ) - utf16_character(document.authored_text, authored)
        if length <= 0:
            continue
        mapped.append(
            SemanticToken(
                line=authored.line,
                character=utf16_character(document.authored_text, authored),
                length=length,
                token_type=token.token_type,
                modifiers=token.modifiers,
            )
        )
    return encode_tokens(sorted(set(mapped)))


def decode_tokens(data: list[int]) -> tuple[SemanticToken, ...]:
    tokens: list[SemanticToken] = []
    line = 0
    character = 0
    for index in range(0, len(data) - 4, 5):
        delta_line, delta_character, length, token_type, modifiers = data[
            index : index + 5
        ]
        line += delta_line
        character = delta_character if delta_line else character + delta_character
        tokens.append(SemanticToken(line, character, length, token_type, modifiers))
    return tuple(tokens)


def encode_tokens(tokens: list[SemanticToken]) -> list[int]:
    data: list[int] = []
    previous_line = 0
    previous_character = 0
    for token in tokens:
        delta_line = token.line - previous_line
        delta_character = (
            token.character if delta_line else token.character - previous_character
        )
        data.extend(
            (
                delta_line,
                delta_character,
                token.length,
                token.token_type,
                token.modifiers,
            )
        )
        previous_line = token.line
        previous_character = token.character
    return data
