from io import BytesIO

from typeforge._result import Ok
from typeforge.proxy.framing import read_message, write_message
from typeforge.proxy.model import JsonObject


class _ChunkedReader(BytesIO):
    def read(self, size: int | None = -1, /) -> bytes:
        requested = -1 if size is None else size
        return super().read(min(requested, 3) if requested >= 0 else 3)


def test_reads_payload_split_across_raw_stream_chunks() -> None:
    message: JsonObject = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "textDocument/hover",
    }
    output = BytesIO()
    assert write_message(output, message) == Ok(None)

    result = read_message(_ChunkedReader(output.getvalue()))

    assert result == Ok(message)
