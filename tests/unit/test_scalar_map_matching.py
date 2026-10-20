"""The approved scalar selector contract through both production consumers."""

from pathlib import Path
from subprocess import run
from sys import executable
from typing import Any, Literal

import pytest
from returns.result import Failure

import typeforge
from pydantic import PydanticSchemaGenerationError, TypeAdapter
from typeforge import Is, Map
from typeforge.compiler.pipeline import generate_module
from typeforge.compiler.source import SourceSyntaxError, parse_source
from typeforge.pydantic import Schema


class Animal:
    pass


class Dog(Animal):
    pass


class UserId(int):
    pass


@pytest.mark.parametrize(
    ("subject", "selector", "expected"),
    [
        (bool, int, "str"),
        (bool, Is[int], "bytes"),
        (Dog, Animal, "str"),
        (Dog, Is[Animal], "bytes"),
        (UserId, int, "str"),
        (UserId, Is[int], "bytes"),
        (int, float, "str"),
        (bool, float, "str"),
        (UserId, complex, "str"),
        (float, int, "bytes"),
        (Any, int, "str"),
        (int, Any, "str"),
        (Any, Is[int], "bytes"),
        (Literal[True], Literal[1], "bytes"),
    ],
)
def test_scalar_runtime_selection(
    subject: object, selector: object, expected: str
) -> None:
    adapter = TypeAdapter[object](Schema[Map[subject, selector:str, ...:bytes]])

    assert adapter.core_schema["type"] == expected


@pytest.mark.parametrize(
    ("subject", "selector", "expected"),
    [
        ("bool", "int", "str"),
        ("bool", "Is[int]", "bytes"),
        ("Dog", "Animal", "str"),
        ("Dog", "Is[Animal]", "bytes"),
        ("UserId", "int", "str"),
        ("UserId", "Is[int]", "bytes"),
        ("int", "float", "str"),
        ("bool", "float", "str"),
        ("UserId", "complex", "str"),
        ("float", "int", "bytes"),
        ("Any", "int", "str"),
        ("int", "Any", "str"),
        ("Any", "Is[int]", "bytes"),
        ("Literal[True]", "Literal[1]", "bytes"),
    ],
)
def test_scalar_compiler_selection(
    tmp_path: Path, subject: str, selector: str, expected: str
) -> None:
    source = tmp_path / "scalar.py"
    source.write_text(
        "from typing import Any, Literal\n"
        "from typeforge import Is, Map\n"
        "from typeforge.pydantic import Schema\n"
        "class Animal: ...\n"
        "class Dog(Animal): ...\n"
        "class UserId(int): ...\n"
        "class Payload:\n"
        f"    value: Schema[Map[{subject}, {selector}: str, ...: bytes]]\n"
    )

    generated = generate_module(source, maximum_arity=1).unwrap()

    assert generated.content.endswith(f"class Payload:\n    value: {expected}\n")


@pytest.mark.parametrize("name", ["Equal", "Assignable", "All", "Any", "Not"])
def test_superseded_selectors_are_not_public(name: str) -> None:
    assert name not in typeforge.__all__
    assert not hasattr(typeforge, name)
    source = f"from typeforge import Map, {name}\ntype Bad = Map[int, {name}[int]: str]"

    result = parse_source(source, Path("authored.py"))

    assert isinstance(result, Failure)
    issue = result.failure()
    assert isinstance(issue, SourceSyntaxError)
    assert "no longer a public selector" in issue.message
    assert issue.span.start.line == 2


def test_is_rejects_binary_authoring_in_both_frontends() -> None:
    with pytest.raises(TypeError, match="Is requires one type argument"):
        Map[int, Is[int, str] : bytes]

    result = parse_source(
        "from typeforge import Is, Map\ntype Bad = Map[int, Is[int, str]: bytes]"
    )

    assert isinstance(result, Failure)
    issue = result.failure()
    assert isinstance(issue, SourceSyntaxError)
    assert issue.message == "Is requires one type argument"


def test_runtime_failure_displays_public_exact_syntax() -> None:
    with pytest.raises(
        PydanticSchemaGenerationError,
        match=r"Map\[bool, Is\[int\]: str\]",
    ):
        TypeAdapter(Schema[Map[bool, Is[int] : str]])


def test_generic_is_alias_uses_its_consuming_subject(tmp_path: Path) -> None:
    type Exact[T] = Is[T]

    assert (
        TypeAdapter(Schema[Map[bool, Exact[int] : str, ...:bytes]]).core_schema["type"]
        == "bytes"
    )
    path = tmp_path / "alias.py"
    path.write_text(
        "from typeforge import Is, Map\n"
        "from typeforge.pydantic import Schema\n"
        "type Exact[T] = Is[T]\n"
        "class Payload:\n"
        "    value: Schema[Map[bool, Exact[int]:str, ...:bytes]]\n"
    )

    assert "value: bytes" in generate_module(path, maximum_arity=1).unwrap().content


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_checkers_consume_scalar_selection(tmp_path: Path, checker: str) -> None:
    library = tmp_path / "scalar_library.py"
    library.write_text(
        "from typeforge import Is, Map\n"
        "from typeforge.pydantic import Schema\n"
        "class Payload:\n"
        "    compatible: Schema[Map[bool, int:str, ...:bytes]]\n"
        "    exact: Schema[Map[bool, Is[int]:str, ...:bytes]]\n"
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
        "from scalar_library import Payload\n"
        "def verify(value: Payload) -> None:\n"
        "    assert_type(value.compatible, str)\n"
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

    consumer.write_text(good + "    invalid: str = value.exact\n    print(invalid)\n")
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "bytes" in rejected.stdout + rejected.stderr
