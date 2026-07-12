from collections.abc import Mapping
from enum import StrEnum

from typeforge.analysis.mapping import authored_to_generated, generated_to_authored
from typeforge.analysis.model import VirtualDocument
from typeforge.analysis.positions import source_position_from_utf16, utf16_character
from typeforge.proxy.model import DocumentState, JsonObject, JsonValue


class MappingDirection(StrEnum):
    AUTHORED_TO_GENERATED = "authored_to_generated"
    GENERATED_TO_AUTHORED = "generated_to_authored"


def map_message_payload(
    value: JsonValue,
    documents: Mapping[str, DocumentState],
    direction: MappingDirection,
    default_uri: str | None = None,
) -> JsonValue:
    if isinstance(value, list):
        return [
            map_message_payload(item, documents, direction, default_uri)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    uri = document_uri(value) or default_uri
    state = documents.get(uri) if uri is not None else None
    document = state.document if state is not None else None
    if document is not None and is_position(value):
        return map_position(value, document, direction)
    mapped: JsonObject = {}
    for key, item in value.items():
        if key in {"command", "data"}:
            mapped[key] = item
        elif key == "changes" and isinstance(item, dict):
            mapped[key] = {
                changed_uri: map_message_payload(
                    edits,
                    documents,
                    direction,
                    changed_uri,
                )
                for changed_uri, edits in item.items()
            }
        else:
            mapped[key] = map_message_payload(item, documents, direction, uri)
    if document is not None and is_folding_range(mapped):
        return map_folding_range(mapped, document, direction)
    return mapped


def map_position(
    value: JsonObject,
    document: VirtualDocument,
    direction: MappingDirection,
) -> JsonObject:
    line = value.get("line")
    character = value.get("character")
    if not isinstance(line, int) or not isinstance(character, int):
        return value
    source = (
        document.authored_text
        if direction is MappingDirection.AUTHORED_TO_GENERATED
        else document.generated_text
    )
    position = source_position_from_utf16(source, line, character)
    mapped = (
        authored_to_generated(document, position)
        if direction is MappingDirection.AUTHORED_TO_GENERATED
        else generated_to_authored(document, position)
    )
    target = (
        document.generated_text
        if direction is MappingDirection.AUTHORED_TO_GENERATED
        else document.authored_text
    )
    return {
        **value,
        "line": mapped.line,
        "character": utf16_character(target, mapped),
    }


def map_folding_range(
    value: JsonObject,
    document: VirtualDocument,
    direction: MappingDirection,
) -> JsonObject:
    start_line = value.get("startLine")
    end_line = value.get("endLine")
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        return value
    start = map_position(
        {
            "line": start_line,
            "character": integer_value(value.get("startCharacter")),
        },
        document,
        direction,
    )
    end = map_position(
        {
            "line": end_line,
            "character": integer_value(value.get("endCharacter")),
        },
        document,
        direction,
    )
    mapped = {
        **value,
        "startLine": start["line"],
        "endLine": end["line"],
    }
    if "startCharacter" in value:
        mapped["startCharacter"] = start["character"]
    if "endCharacter" in value:
        mapped["endCharacter"] = end["character"]
    return mapped


def document_uri(value: JsonObject) -> str | None:
    uri = value.get("uri")
    if isinstance(uri, str):
        return uri
    text_document = value.get("textDocument")
    if isinstance(text_document, dict):
        nested_uri = text_document.get("uri")
        if isinstance(nested_uri, str):
            return nested_uri
    return None


def is_position(value: JsonObject) -> bool:
    return isinstance(value.get("line"), int) and isinstance(
        value.get("character"), int
    )


def is_folding_range(value: JsonObject) -> bool:
    return isinstance(value.get("startLine"), int) and isinstance(
        value.get("endLine"), int
    )


def integer_value(value: JsonValue) -> int:
    return value if isinstance(value, int) else 0
