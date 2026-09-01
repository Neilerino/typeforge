from io import BytesIO

import pytest
from returns.result import Failure, Success

from typeforge.utils.stream import (
    JsonObject,
    read_lsp_message,
    write_lsp_message,
)


class _ChunkedReader(BytesIO):
    def read(self, size: int | None = -1, /) -> bytes:
        requested = -1 if size is None else size
        return super().read(min(requested, 3) if requested >= 0 else 3)


def test_round_trips_chunked_messages() -> None:
    messages: tuple[JsonObject, ...] = (
        {"jsonrpc": "2.0", "id": 1, "result": None},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
    )
    output = BytesIO()
    for message in messages:
        assert write_lsp_message(output, message) == Success(None)

    reader = _ChunkedReader(output.getvalue())

    assert read_lsp_message(reader) == Success(messages[0])
    assert read_lsp_message(reader) == Success(messages[1])
    assert read_lsp_message(reader) == Success(None)


@pytest.mark.parametrize(
    ("payload", "detail"),
    (
        (b"Broken\r\n\r\n", "invalid LSP header"),
        (b"Content-Length: 2\r\n", "unexpected end of stream"),
        (b"Other: 2\r\n\r\n{}", "missing Content-Length"),
        (b"Content-Length: no\r\n\r\n", "invalid Content-Length"),
        (b"Content-Length: -1\r\n\r\n{}", "invalid Content-Length"),
        (b"Content-Length: 10\r\n\r\n{}", "truncated LSP message"),
        (b"Content-Length: 2\r\n\r\n[]", "JSON-RPC payload must be an object"),
    ),
)
def test_reports_invalid_frames_as_typed_failures(payload: bytes, detail: str) -> None:
    result = read_lsp_message(BytesIO(payload))

    assert isinstance(result, Failure)
    assert detail in result.failure().message
