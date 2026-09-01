# pyright: reportPrivateUsage=false

from returns.result import Success

from typeforge.adapters.lsp import (
    LspDiagnostic,
    LspPosition,
    LspRange,
    _parse_diagnostic_report,
    _published_diagnostics,
)
from typeforge.utils.stream import JsonObject


def _diagnostic(line: int, message: str) -> JsonObject:
    return {
        "range": {
            "start": {"line": line, "character": 0},
            "end": {"line": line, "character": 1},
        },
        "severity": 2,
        "message": message,
    }


def test_published_diagnostics_are_classified_and_mapped_to_domain_data() -> None:
    uri = "file:///example.py"
    message: JsonObject = {
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {
            "uri": uri,
            "diagnostics": [_diagnostic(1, "first"), _diagnostic(2, "second")],
        },
    }

    result = _published_diagnostics(message, uri)

    assert result == Success(
        (
            LspDiagnostic(
                LspRange(LspPosition(1, 0), LspPosition(1, 1)),
                "first",
                severity=2,
            ),
            LspDiagnostic(
                LspRange(LspPosition(2, 0), LspPosition(2, 1)),
                "second",
                severity=2,
            ),
        )
    )


def test_unrelated_message_is_not_a_diagnostic_protocol_error() -> None:
    message: JsonObject = {"jsonrpc": "2.0", "id": 1, "result": None}

    assert _published_diagnostics(message, "file:///example.py") == Success(None)


def test_pull_diagnostic_report_uses_the_same_wire_conversion() -> None:
    result = _parse_diagnostic_report(
        {"kind": "full", "items": [_diagnostic(3, "pulled")]}
    )

    assert result == Success(
        (
            LspDiagnostic(
                LspRange(LspPosition(3, 0), LspPosition(3, 1)),
                "pulled",
                severity=2,
            ),
        )
    )
