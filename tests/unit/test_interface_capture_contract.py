"""Compatible interface captures preserve actual element types."""

from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from returns.result import Failure, Success

from pydantic import PydanticSchemaGenerationError, TypeAdapter
from typeforge.compiler.pipeline import AdaptationError, generate_module
from typeforge.pydantic import Schema


def test_list_element_is_captured_through_sequence(tmp_path: Path) -> None:
    program = (
        "from collections.abc import Sequence\n"
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Element[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[T, Sequence[Item]: Item, ...: bytes]\n"
    )
    source = tmp_path / "elements.py"
    source.write_text(program + "class Payload:\n    value: Element[list[int]]\n")
    generated = generate_module(source, maximum_arity=1)
    assert isinstance(generated, Success)
    assert generated.unwrap().content.endswith("class Payload:\n    value: int\n")

    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    specialized: object = eval("Element[list[int]]", namespace)
    assert TypeAdapter(Schema[specialized]).validate_python("4") == 4


@pytest.mark.parametrize(
    ("subject", "selector", "output", "expected"),
    [
        ("list[bool]", "Sequence[Item]", "Item", "bool"),
        ("tuple[str, ...]", "Sequence[Item]", "Item", "str"),
        ("tuple[int, str]", "Sequence[Item]", "Item", "int | str"),
        ("list[int | str]", "Sequence[Item]", "Item", "int | str"),
        ("Sequence[int]", "Sequence[Item]", "Item", "int"),
        ("list[int]", "Items[Item]", "Item", "int"),
        ("tuple[bool, str]", "TypingSequence[Item]", "Item", "bool | str"),
        ("int", "Sequence[Item]", "Item", "bytes"),
        ("set[int]", "Sequence[Item]", "Item", "bytes"),
        (
            "list[int] | tuple[str, ...]",
            "Sequence[Item]",
            "tuple[Item, Item]",
            "tuple[int, int] | tuple[str, str]",
        ),
        (
            "tuple[int, str]",
            "Sequence[Item]",
            "Map[Item, int: bool, str: float]",
            "bool | float",
        ),
        (
            "tuple[list[int], int]",
            "tuple[Sequence[Item], Item]",
            "Item",
            "int",
        ),
        (
            "tuple[list[bool], int]",
            "tuple[Sequence[Item], Item]",
            "Item",
            "bytes",
        ),
        (
            "tuple[list[int | str], str | int]",
            "tuple[Sequence[Item], Item]",
            "Item",
            "int | str",
        ),
        (
            "list[Any | str]",
            "Sequence[Item]",
            "Map[Item, Is[Any | str]: bool, ...: float]",
            "bool",
        ),
        (
            "list[int] | set[str]",
            "Sequence[Item]",
            "tuple[Item]",
            "tuple[int] | bytes",
        ),
    ],
)
def test_interface_capture_preserves_complete_outputs_in_both_consumers(
    tmp_path: Path, subject: str, selector: str, output: str, expected: str
) -> None:
    program = (
        "from collections.abc import Sequence\n"
        "from collections.abc import Sequence as Items\n"
        "from typing import Any, Sequence as TypingSequence\n"
        "from typeforge import Capture, Is, Map, type_function\n"
        "@type_function\n"
        "def Selected():\n"
        '    Item = Capture("Item")\n'
        f"    return Map[{subject}, {selector}: {output}, ...: bytes]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    expected_type: object = eval(expected, namespace)
    assert (
        TypeAdapter(Schema[namespace["Selected"]]).json_schema()
        == TypeAdapter(expected_type).json_schema()
    )
    source = tmp_path / "selected.py"
    source.write_text(program + "class Payload:\n    value: Selected\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert generated.content.endswith(f"class Payload:\n    value: {expected}\n")


def test_interface_capture_retains_known_generic_positions(tmp_path: Path) -> None:
    program = (
        "from collections.abc import Sequence\n"
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Elements[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[tuple[T, int], Sequence[Item]: tuple[Item]]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    specialized: object = eval("Elements[str]", namespace)
    assert (
        TypeAdapter(Schema[specialized]).json_schema()
        == TypeAdapter(tuple[str | int]).json_schema()
    )
    source = tmp_path / "known_shape.py"
    source.write_text(program + "class Payload:\n    value: Elements[str]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "type Elements[T] = tuple[T | int]" in generated.content
    assert generated.content.endswith("class Payload:\n    value: tuple[str | int]\n")


@pytest.mark.parametrize(
    ("subject", "output", "message"),
    [
        ("list[int] | set[str]", "Item", "no case matched"),
        ("Box[int]", "Item", "supported interface capture"),
        ("list[int]", "Other", "unbound"),
    ],
)
def test_interface_capture_failure_is_not_hidden_by_fallback(
    tmp_path: Path, subject: str, output: str, message: str
) -> None:
    fallback = "" if subject == "list[int] | set[str]" else ", ...: bytes"
    program = (
        "from collections.abc import Sequence\n"
        "from typeforge import Capture, Map, type_function\n"
        "class Box[T]: ...\n"
        "@type_function\n"
        "def Selected():\n"
        '    Item = Capture("Item")\n'
        '    Other = Capture("Item")\n'
        f"    return Map[{subject}, Sequence[Item]: {output}{fallback}]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    with pytest.raises(PydanticSchemaGenerationError):
        TypeAdapter(Schema[namespace["Selected"]])

    source = tmp_path / "unsupported.py"
    source.write_text(program)
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    issue = result.failure()
    assert isinstance(issue, AdaptationError)
    assert message in issue.message
    assert issue.declaration == "Selected"
    assert issue.expression.startswith(f"Map[{subject}, Sequence[Item]")


def test_opaque_parameter_keeps_a_sound_bound_and_precise_specializations(
    tmp_path: Path,
) -> None:
    source = tmp_path / "opaque.py"
    source.write_text(
        "from collections.abc import Sequence\n"
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Element[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[T, Sequence[Item]: Item, ...: bytes]\n"
        "class Payload:\n"
        "    element: Element[list[bool]]\n"
        "    mixed: Element[tuple[int, str]]\n"
        "    fallback: Element[int]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "type Element[T] = object" in generated.content
    assert generated.content.endswith(
        "class Payload:\n    element: bool\n    mixed: int | str\n    fallback: bytes\n"
    )


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_interface_capture_outputs_are_checked_by_existing_checkers(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "elements.py"
    source.write_text(
        "from collections.abc import Sequence\n"
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Pair[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[T, Sequence[Item]: tuple[Item, Item], ...: bytes]\n"
        "class Payload:\n"
        "    mixed: Pair[tuple[int, str]]\n"
        "    correlated: Pair[list[int] | tuple[str, ...]]\n"
        "    flags: Pair[list[bool]]\n"
    )
    source.with_suffix(".pyi").write_text(
        generate_module(source, maximum_arity=1).unwrap().content
    )
    (tmp_path / "pyrefly.toml").write_text(
        'python-version = "3.14"\nsearch-path = ["."]\n'
    )
    (tmp_path / "pyrightconfig.json").write_text(
        '{"pythonVersion": "3.14", "typeCheckingMode": "strict"}'
    )
    consumer = tmp_path / "consumer.py"
    good = (
        "from typing import assert_type\n"
        "from elements import Payload\n"
        "def check(value: Payload) -> None:\n"
        "    assert_type(value.mixed, tuple[int | str, int | str])\n"
        "    assert_type(value.correlated, tuple[int, int] | tuple[str, str])\n"
        "    assert_type(value.flags, tuple[bool, bool])\n"
    )
    consumer.write_text(good)
    commands = {
        "mypy": (executable, "-m", "mypy", "--strict", "--config-file", "/dev/null"),
        "pyright": (executable, "-m", "pyright", "--pythonpath", executable),
        "pyrefly": (str(Path(executable).with_name("pyrefly")), "check"),
    }
    accepted = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    consumer.write_text(
        good
        + "def reject(value: Payload) -> tuple[int, str]:\n"
        + "    return value.correlated\n"
    )
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "tuple" in rejected.stdout + rejected.stderr
