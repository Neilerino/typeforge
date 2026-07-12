from pathlib import Path

from typeforge._result import Ok
from typeforge.compiler.pipeline import generate_module

FIXTURES = Path(__file__).parent / "fixtures"


def test_conditionals_maps_and_record_maps_compile_to_portable_stubs() -> None:
    generated = generate_module(FIXTURES / "pipeline_syntax.py", maximum_arity=2)

    assert isinstance(generated, Ok)
    assert generated.value.content == (
        "from datetime import datetime\n"
        "from typing import Literal, Never, TypedDict, overload\n\n"
        "class User(TypedDict):\n"
        "    name: str\n"
        "    created_at: datetime\n"
        "    attempts: int\n\n"
        "class JsonSafe_User(TypedDict):\n"
        "    name: str\n"
        "    created_at: str\n"
        "    attempts: int\n\n"
        "@overload\n"
        'def read(mode: Literal["text"]) -> str: ...\n'
        "@overload\n"
        "def read[M](mode: M) -> str | bytes: ...\n\n"
        "@overload\n"
        "def serialize(value: int) -> float: ...\n"
        "@overload\n"
        "def serialize(value: bytes) -> str: ...\n"
        "@overload\n"
        "def serialize[T](value: T) -> float | str | T: ...\n\n"
        "@overload\n"
        "def strict_serialize(value: int) -> str: ...\n"
        "@overload\n"
        "def strict_serialize[T](value: T) -> str | Never: ...\n\n"
        "type JsonSafe[T] = object\n\n"
        "@overload\n"
        "def jsonify(value: User) -> JsonSafe_User: ...\n"
        "@overload\n"
        "def jsonify[T](value: T) -> object: ...\n"
    )


def test_existing_each_collect_pipeline_remains_supported() -> None:
    generated = generate_module(FIXTURES / "pipeline.py", maximum_arity=1)

    assert isinstance(generated, Ok)
    assert "def combine[T1](parsers_1: Parser[T1], /)" in generated.value.content


def test_field_maps_can_drop_fields_and_change_modifiers(tmp_path: Path) -> None:
    source = tmp_path / "records.py"
    source.write_text(
        """
from typing import Literal, TypedDict
from typeforge import (
    Drop, Equal, If, Key, MapFields, OptionalField, ReadonlyField, Value
)

class Credentials(TypedDict):
    password: str
    token: str
    attempts: int

type Public[T] = MapFields[
    T,
    If[
        Equal[Key, Literal[\"password\"]],
        Drop,
        If[
            Equal[Key, Literal[\"token\"]],
            ReadonlyField[Key, Value],
            OptionalField[Key, Value],
        ],
    ],
]

def publicize[T](value: T) -> Public[T]:
    raise NotImplementedError
""".lstrip(),
        encoding="utf-8",
    )

    generated = generate_module(source, maximum_arity=2)

    assert isinstance(generated, Ok)
    assert "class Public_Credentials(TypedDict):" in generated.value.content
    assert (
        "    password:"
        not in generated.value.content.split("class Public_Credentials(TypedDict):", 1)[
            1
        ]
    )
    assert "    token: ReadOnly[str]" in generated.value.content
    assert "    attempts: NotRequired[int]" in generated.value.content
