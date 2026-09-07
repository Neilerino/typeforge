"""THROWAWAY: run with `uv run python scripts/slice_map_poc.py`."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypeVar, get_args

from pydantic import BaseModel, TypeAdapter
from typeforge import Assignable, Value
from typeforge import Map as RawMap
from typeforge._slice_map_prototype import Map
from typeforge.compiler.pipeline import generate_module
from typeforge.compiler.source import parse_source
from typeforge.pydantic import Input, Schema

SOURCE = """\
from typeforge import Map

type Encoded[T] = Map[T, int: str, ...: T]

def encode[T](value: T) -> Encoded[T]:
    if type(value) is int:
        return str(value)
    return value
"""


def main() -> None:
    T = TypeVar("T")
    raw = RawMap[T, int : list[T], ...:T]
    normalized = Map[T, int : list[T], ...:T]
    print("PYTHON SUBSTITUTION")
    print("Raw slices: ", raw[int])
    print("Normalized: ", normalized[int])
    print("Existing arguments:", get_args(normalized[int]))

    print("\nSOURCE PARSER")
    alias = parse_source(SOURCE).unwrap().source.aliases[0]
    print(alias.value)

    print("\nPUBLISHED STUB")
    with TemporaryDirectory(prefix="typeforge-slice-poc-") as directory:
        path = Path(directory) / "example.py"
        path.write_text(SOURCE)
        print(generate_module(path, maximum_arity=2).unwrap().content)

    print("PYDANTIC GENERIC MODEL")

    class Payload[T](BaseModel):
        value: Schema[Map[T, int : list[T], ...:T]]

    print(Payload[int](value=["1", "2"]).model_dump())
    print(Payload[str](value="text").model_dump())

    print("\nSTRUCTURAL CAPTURE")
    captured = TypeAdapter(Schema[Map[list[int], list[Value] : tuple[Value, ...]]])
    print(captured.validate_python(["1", 2]))

    print("\nRAW INPUT DISPATCH")
    dispatched = TypeAdapter(
        Schema[Map[Input, str:int, Assignable[int] : float, ...:bytes]]
    )
    for value in ("3", 3, True):
        output = dispatched.validate_python(value)
        print(f"{value!r} -> {output!r} ({type(output).__name__})")


if __name__ == "__main__":
    main()
