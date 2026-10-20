"""Approved union selection, whole-subject Is, and no-match contracts."""

from pathlib import Path
from subprocess import run
from sys import executable
from typing import Never

import pytest
from returns.result import Failure

from pydantic import PydanticSchemaGenerationError, TypeAdapter
from typeforge import Is, Map
from typeforge.compiler.adaptation import AdaptationError
from typeforge.compiler.pipeline import generate_module
from typeforge.pydantic import Schema


@pytest.mark.parametrize(
    ("authored", "runtime", "expected", "emitted"),
    [
        (
            "Map[int | str, int: bytes, str: float]",
            Map[int | str, int:bytes, str:float],
            bytes | float,
            "bytes | float",
        ),
        (
            "Map[int | str, int | str: bytes, ...: float]",
            Map[int | str, int | str : bytes, ...:float],
            bytes,
            "bytes",
        ),
        (
            "Map[int | str, Is[str | int]: bytes, ...: float]",
            Map[int | str, Is[str | int] : bytes, ...:float],
            bytes,
            "bytes",
        ),
        (
            "Map[int | str, int: bytes, Is[str | int]: float]",
            Map[int | str, int:bytes, Is[str | int] : float],
            bytes | float,
            "bytes | float",
        ),
        (
            "Map[int | str, int: bytes, Is[str]: float, ...: bool]",
            Map[int | str, int:bytes, Is[str] : float, ...:bool],
            bytes | bool,
            "bytes | bool",
        ),
        (
            "Map[list[int | str], Is[list[str | int]]: bytes, ...: float]",
            Map[list[int | str], Is[list[str | int]] : bytes, ...:float],
            bytes,
            "bytes",
        ),
        (
            "Map[int | str, Is[str | int | str]: bytes, ...: float]",
            Map[int | str, Is[str | int | str] : bytes, ...:float],
            bytes,
            "bytes",
        ),
        (
            "Map[int, int: bytes, ...: Map[str, int: float]]",
            Map[int, int:bytes, ... : Map[str, int:float]],
            bytes,
            "bytes",
        ),
        (
            "Map[int | str, int: Never, ...: bytes]",
            Map[int | str, int:Never, ...:bytes],
            bytes,
            "bytes",
        ),
        (
            "Map[int, int: Never] | str",
            Map[int, int:Never] | str,
            str,
            "str",
        ),
    ],
)
def test_union_selection_in_both_consumers(
    tmp_path: Path, authored: str, runtime: object, expected: object, emitted: str
) -> None:
    actual = TypeAdapter(Schema[runtime]).json_schema()
    assert actual == TypeAdapter(expected).json_schema()
    source = tmp_path / "union.py"
    source.write_text(
        "from typing import Never\n"
        "from typeforge import Is, Map\n"
        "from typeforge.pydantic import Schema\n"
        "class Payload:\n"
        f"    value: Schema[{authored}]\n"
    )

    generated = generate_module(source, maximum_arity=1).unwrap()

    assert generated.content.endswith(f"class Payload:\n    value: {emitted}\n")


@pytest.mark.parametrize(
    ("authored", "runtime"),
    [
        ("Map[int | str, int: bytes]", Map[int | str, int:bytes]),
        ("Map[int | str, int: bytes] | float", Map[int | str, int:bytes] | float),
        ("list[Map[int | str, int: bytes]]", list[Map[int | str, int:bytes]]),
        ("Map[float, int: bytes]", Map[float, int:bytes]),
    ],
)
def test_known_uncovered_subject_fails_entire_expression(
    tmp_path: Path, authored: str, runtime: object
) -> None:
    with pytest.raises(PydanticSchemaGenerationError, match="map_no_match"):
        TypeAdapter(Schema[runtime])

    source = tmp_path / "uncovered.py"
    source.write_text(
        "from typeforge import Map\n"
        "from typeforge.pydantic import Schema\n"
        "class Payload:\n"
        f"    value: Schema[{authored}]\n"
    )

    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    issue = result.failure()
    assert isinstance(issue, AdaptationError)
    assert "no case matched" in issue.message
    assert issue.expression == f"Schema[{authored}]"


def test_uncovered_field_transform_preserves_authored_failure(tmp_path: Path) -> None:
    source = tmp_path / "record.py"
    transform = (
        "Record((Field[field.name, Map[field.type, int:bytes]] for field in Fields[T]))"
    )
    source.write_text(
        f"""\
from typing import TypedDict
from typeforge import Field, Map, Fields, Record
class Source(TypedDict):
    value: int | str
type Transform[T] = {transform}
def read(value: Transform[Source]) -> None: ...
"""
    )

    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    issue = result.failure()
    assert issue.expression == transform
    assert "no case matched" in issue.message


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_checkers_consume_selected_union_outputs(tmp_path: Path, checker: str) -> None:
    library = tmp_path / "union_library.py"
    library.write_text(
        "from typeforge import Is, Map\n"
        "from typeforge.pydantic import Schema\n"
        "class Payload:\n"
        "    distributed: Schema[Map[int | str, int: bytes, str: float]]\n"
        "    exact: Schema[Map[int | str, Is[str | int]: bytes, ...: float]]\n"
    )
    library.with_suffix(".pyi").write_text(
        generate_module(library, maximum_arity=1).unwrap().content
    )
    (tmp_path / "pyrefly.toml").write_text(
        'python-version = "3.14"\nsearch-path = ["."]\n'
    )
    (tmp_path / "pyrightconfig.json").write_text(
        '{"pythonVersion": "3.14", "typeCheckingMode": "strict"}'
    )
    commands = {
        "mypy": (executable, "-m", "mypy", "--strict", "--config-file", "/dev/null"),
        "pyright": (executable, "-m", "pyright", "--pythonpath", executable),
        "pyrefly": (str(Path(executable).with_name("pyrefly")), "check"),
    }
    consumer = tmp_path / "consumer.py"
    good = (
        "from typing import assert_type\n"
        "from union_library import Payload\n"
        "def verify(value: Payload) -> None:\n"
        "    assert_type(value.distributed, bytes | float)\n"
        "    assert_type(value.exact, bytes)\n"
    )
    consumer.write_text(good)
    accepted = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    consumer.write_text(
        good + "    invalid: bytes = value.distributed\n    print(invalid)\n"
    )
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "float" in rejected.stdout + rejected.stderr
