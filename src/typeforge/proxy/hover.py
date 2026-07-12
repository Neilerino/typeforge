from typeforge.proxy.model import JsonObject, JsonValue


def append_hover_documentation(message: JsonObject, documentation: str) -> JsonObject:
    if "error" in message:
        return message
    result = _object(message.get("result"))
    if result is None:
        return {
            **message,
            "result": {
                "contents": {"kind": "markdown", "value": documentation},
            },
        }
    contents = result.get("contents")
    return {
        **message,
        "result": {
            **result,
            "contents": _append_contents(contents, documentation),
        },
    }


def _append_contents(contents: JsonValue, documentation: str) -> JsonValue:
    markup = _object(contents)
    if markup is not None:
        kind = markup.get("kind")
        value = markup.get("value")
        if kind == "markdown" and isinstance(value, str):
            return {**markup, "value": _join(value, documentation)}
        if kind == "plaintext" and isinstance(value, str):
            return {
                "kind": "markdown",
                "value": _join(_fenced_plaintext(value), documentation),
            }
        return [markup, documentation]
    if isinstance(contents, str):
        return _join(contents, documentation)
    if isinstance(contents, list):
        return [*contents, documentation]
    return {"kind": "markdown", "value": documentation}


def _join(existing: str, documentation: str) -> str:
    if not existing:
        return documentation
    return f"{existing}\n\n---\n\n{documentation}"


def _fenced_plaintext(value: str) -> str:
    fence = "```"
    while fence in value:
        fence += "`"
    return f"{fence}text\n{value}\n{fence}"


def _object(value: JsonValue) -> JsonObject | None:
    return value if isinstance(value, dict) else None
