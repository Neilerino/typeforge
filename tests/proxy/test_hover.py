from typeforge.proxy.hover import append_hover_documentation
from typeforge.proxy.model import JsonObject


def test_appends_documentation_to_markdown_hover() -> None:
    message: JsonObject = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "contents": {"kind": "markdown", "value": "```python\nEach[T]\n```"},
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 4},
            },
        },
    }

    result = append_hover_documentation(message, "Captures each argument.")

    assert result["result"] == {
        "contents": {
            "kind": "markdown",
            "value": "```python\nEach[T]\n```\n\n---\n\nCaptures each argument.",
        },
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 4},
        },
    }


def test_creates_hover_when_checker_has_no_result() -> None:
    result = append_hover_documentation(
        {"jsonrpc": "2.0", "id": 1, "result": None},
        "A documented type.",
    )

    assert result["result"] == {
        "contents": {"kind": "markdown", "value": "A documented type."}
    }


def test_preserves_plaintext_as_literal_markdown() -> None:
    result = append_hover_documentation(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"contents": {"kind": "plaintext", "value": "A `value`"}},
        },
        "Useful **documentation**.",
    )

    assert result["result"] == {
        "contents": {
            "kind": "markdown",
            "value": ("```text\nA `value`\n```\n\n---\n\nUseful **documentation**."),
        }
    }


def test_preserves_language_marked_string_hover() -> None:
    marked_string: JsonObject = {"language": "python", "value": "Each[T]"}

    result = append_hover_documentation(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"contents": marked_string},
        },
        "Captures each argument.",
    )

    assert result["result"] == {"contents": [marked_string, "Captures each argument."]}


def test_preserves_checker_hover_error() -> None:
    message: JsonObject = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32603, "message": "Hover failed"},
    }

    assert append_hover_documentation(message, "Documentation") == message
