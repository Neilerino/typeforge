"""Transparent aliases and explicit Any union selection through both frontends."""

from pathlib import Path
from subprocess import run
from sys import executable
from typing import Annotated

import pytest
from returns.result import Failure

from pydantic import Field, PydanticSchemaGenerationError, TypeAdapter, ValidationError
from typeforge import Is, Map
from typeforge.compiler.pipeline import generate_module
from typeforge.pydantic import Schema


@pytest.mark.parametrize(
    ("aliases", "expression", "expected"),
    [
        (
            "type Numbers = int | str",
            "Map[Numbers, int: bytes, ...: float]",
            "bytes | float",
        ),
        ("type Numbers = int | str", "Map[int, Numbers: bytes, ...: float]", "bytes"),
        (
            "type Numbers = int | str",
            "Map[Numbers, Is[str | int]: bytes, ...: float]",
            "bytes",
        ),
        (
            "type Items[T] = list[T]",
            "Map[Items[int], Is[list[int]]: bytes, ...: float]",
            "bytes",
        ),
        (
            "type Items[T] = list[T]",
            "Map[list[int], Is[Items[int]]: bytes, ...: float]",
            "bytes",
        ),
        (
            "type Item = int",
            "Map[list[Item], Is[list[int]]: bytes, ...: float]",
            "bytes",
        ),
        (
            "type Identity[T] = T",
            "Map[Identity[Identity[int]], Is[int]: bytes, ...: float]",
            "bytes",
        ),
        (
            "type Items[T] = list[T]\n"
            "type Selected[T] = Map[Items[T], Is[list[T]]: bytes, ...: float]",
            "Selected[int]",
            "bytes",
        ),
        ("", "Map[Any | int, Is[Any]: bytes, ...: str]", "str"),
        ("", "Map[int, int: Any | str]", "Any | str"),
        (
            "",
            "Map[Map[int, int: Any | str], Is[str | Any]: bytes, ...: float]",
            "bytes",
        ),
        ("", "Map[Map[int, int: Any | str], Is[Any]: bytes, ...: float]", "float"),
        (
            "type Mixed = Any | str",
            "Map[Mixed, Is[str | Any]: bytes, ...: float]",
            "bytes",
        ),
        (
            "type Mixed = Any | str",
            "Map[Map[int, int: Mixed], Is[str | Any]: bytes, ...: float]",
            "bytes",
        ),
        (
            "type Mixed = Any | str",
            "Map[Map[int, int: Mixed], Is[Any]: bytes, ...: float]",
            "float",
        ),
        (
            "type Mixed = Any | str",
            "Map[list[Mixed], Is[list[str | Any]]: bytes, ...: float]",
            "bytes",
        ),
        ("", "Map[Any | int, int: str, ...: bytes]", "str"),
        (
            'UserId = NewType("UserId", int)\ntype Alias = UserId',
            "Map[Alias, Is[int]: str, ...: bytes]",
            "bytes",
        ),
    ],
)
def test_alias_and_any_selection_parity(
    tmp_path: Path, aliases: str, expression: str, expected: str
) -> None:
    imports = (
        "from typing import Any, NewType\n"
        "from typeforge import Is, Map\n"
        "from typeforge.pydantic import Schema\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(imports + aliases, namespace)
    annotation: object = eval(expression, namespace)
    result_type: object = eval(expected, namespace)
    assert (
        TypeAdapter(Schema[annotation]).json_schema()
        == TypeAdapter(result_type).json_schema()
    )
    source = tmp_path / "aliases.py"
    source.write_text(
        imports + aliases + "\nclass Payload:\n" + f"    value: Schema[{expression}]\n"
    )

    generated = generate_module(source, maximum_arity=1).unwrap()

    assert generated.content.endswith(f"class Payload:\n    value: {expected}\n")


@pytest.mark.parametrize(
    "expression", ["Map[Cycle, int: str]", "Map[int, Is[Cycle]: str]"]
)
def test_selection_alias_cycles_are_authored_failures(
    tmp_path: Path, expression: str
) -> None:
    type Cycle = list[Cycle]
    with pytest.raises(PydanticSchemaGenerationError, match="alias_cycle"):
        TypeAdapter(Schema[eval(expression, {"Cycle": Cycle, "Map": Map, "Is": Is})])

    source = tmp_path / "cycle.py"
    source.write_text(
        "from typeforge import Is, Map\n"
        "from typeforge.pydantic import Schema\n"
        "type Cycle = list[Cycle]\n"
        "class Payload:\n"
        f"    value: Schema[{expression}]\n"
    )
    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    assert "cyclic schema alias" in result.failure().message
    assert result.failure().expression == f"Schema[{expression}]"


def test_output_alias_metadata_is_delegated_to_pydantic() -> None:
    type Positive = Annotated[int, Field(gt=0)]
    adapter = TypeAdapter(Schema[Map[int, int:Positive]])

    assert adapter.json_schema() == TypeAdapter(Positive).json_schema()
    assert adapter.validate_python("2") == 2
    with pytest.raises(ValidationError):
        adapter.validate_python(-1)


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_checkers_consume_alias_and_any_selection(tmp_path: Path, checker: str) -> None:
    library = tmp_path / "alias_library.py"
    library.write_text(
        "from typing import Any\n"
        "from typeforge import Is, Map\n"
        "from typeforge.pydantic import Schema\n"
        "type Numbers = int | str\n"
        "type Mixed = Any | str\n"
        "class Payload:\n"
        "    aliased: Schema[Map[Numbers, int: bytes, ...: float]]\n"
        "    exact: Schema[Map[Mixed, Is[str | Any]: bytes, ...: float]]\n"
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
        "from alias_library import Payload\n"
        "def verify(value: Payload) -> None:\n"
        "    assert_type(value.aliased, bytes | float)\n"
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

    consumer.write_text(good + "    invalid: float = value.exact\n    print(invalid)\n")
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "bytes" in rejected.stdout + rejected.stderr
