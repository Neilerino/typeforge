"""Alternative patterns instantiate complete outputs in isolated scopes."""

from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from returns.result import Failure

from pydantic import PydanticSchemaGenerationError, TypeAdapter, ValidationError
from typeforge.compiler.pipeline import AdaptationError, generate_module
from typeforge.pydantic import Schema


def test_overlapping_alternatives_keep_correlated_outputs(tmp_path: Path) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Repeated[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[T, tuple[Item, str] | tuple[int, Item]: "
        "tuple[Item, Item], ...: bytes]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    specialized: object = eval("Repeated[tuple[int, str]]", namespace)
    adapter = TypeAdapter(Schema[specialized])
    assert (
        adapter.json_schema()
        == TypeAdapter(tuple[int, int] | tuple[str, str]).json_schema()
    )
    assert adapter.validate_python((1, 2), strict=True) == (1, 2)
    assert adapter.validate_python(("a", "b"), strict=True) == ("a", "b")
    with pytest.raises(ValidationError):
        adapter.validate_python((1, "a"), strict=True)

    source = tmp_path / "alternatives.py"
    source.write_text(
        program + "class Payload:\n    value: Repeated[tuple[int, str]]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert generated.content.endswith(
        "class Payload:\n    value: tuple[int, int] | tuple[str, str]\n"
    )


@pytest.mark.parametrize(
    ("subject", "selector", "output", "expected"),
    [
        (
            "list[int]",
            "list[Item] | tuple[Item, ...]",
            "set[Item]",
            "set[int]",
        ),
        (
            "tuple[str, ...]",
            "list[Item] | tuple[Item, ...]",
            "set[Item]",
            "set[str]",
        ),
        (
            "list[int] | tuple[str, ...]",
            "list[Item] | tuple[Item, ...]",
            "tuple[Item, Item]",
            "tuple[int, int] | tuple[str, str]",
        ),
        (
            "tuple[int, str]",
            "tuple[int, Item] | tuple[Item, str]",
            "tuple[Item, Item]",
            "tuple[str, str] | tuple[int, int]",
        ),
        (
            "tuple[int, int]",
            "tuple[Item, Item] | list[Item]",
            "Item",
            "int",
        ),
        (
            "tuple[int, bool]",
            "tuple[Item, Item] | list[Item]",
            "Item",
            "bytes",
        ),
        (
            "tuple[int, str]",
            "tuple[Item, Item] | tuple[Other, Item]",
            "Item",
            "str",
        ),
        (
            "tuple[tuple[int, str]]",
            "tuple[tuple[Item, str] | tuple[int, Item]]",
            "tuple[Item, Item]",
            "tuple[int, int] | tuple[str, str]",
        ),
        (
            "tuple[tuple[int, str], str]",
            "tuple[tuple[Item, str] | tuple[int, Item], Item]",
            "tuple[Item, Item]",
            "tuple[str, str]",
        ),
        (
            "tuple[tuple[int, str], bytes]",
            "tuple[tuple[Item, str] | tuple[int, Item], Item]",
            "tuple[Item, Item]",
            "bytes",
        ),
        (
            "list[int] | tuple[int, str]",
            "Sequence[Item] | tuple[Other, Item]",
            "tuple[Item, Item]",
            "tuple[int, int] | tuple[int | str, int | str] | tuple[str, str]",
        ),
        (
            "bool",
            "list[Item] | int",
            "str",
            "str",
        ),
        (
            "list[int | str]",
            "list[Item] | tuple[Item, ...]",
            "Map[Item, Is[int | str]: bool, ...: float]",
            "bool",
        ),
        (
            "tuple[int, str]",
            "tuple[Item, str] | tuple[int, Item]",
            "Map[Item, int: tuple[Item, Item], ...: list[Item]]",
            "tuple[int, int] | list[str]",
        ),
        (
            "list[int]",
            "list[Item]",
            "Map[tuple[int, str], tuple[Item, str] | tuple[int, Item]: Item]",
            "int",
        ),
    ],
)
def test_alternatives_preserve_bindings_and_complete_outputs(
    tmp_path: Path, subject: str, selector: str, output: str, expected: str
) -> None:
    program = (
        "from collections.abc import Sequence\n"
        "from typeforge import Capture, Is, Map, type_function\n"
        "@type_function\n"
        "def Selected():\n"
        '    Item = Capture("Item")\n'
        '    Other = Capture("Item")\n'
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


@pytest.mark.parametrize(
    ("subject", "selector", "output"),
    [
        ("int", "list[Item] | int", "Item"),
        ("bool", "list[Item] | int", "Item"),
        (
            "tuple[int, str]",
            "tuple[Item, str] | tuple[int, Other]",
            "tuple[Item, Other]",
        ),
        ("tuple[int, str]", "tuple[Item, str] | tuple[int, str]", "Item"),
    ],
)
def test_missing_capture_on_any_matching_alternative_is_an_error(
    tmp_path: Path, subject: str, selector: str, output: str
) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Selected():\n"
        '    Item = Capture("Item")\n'
        '    Other = Capture("Item")\n'
        f"    return Map[{subject}, {selector}: {output}, ...: bytes]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    with pytest.raises(PydanticSchemaGenerationError, match="unbound_capture"):
        TypeAdapter(Schema[namespace["Selected"]])

    source = tmp_path / "unbound.py"
    source.write_text(program)
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    issue = result.failure()
    assert isinstance(issue, AdaptationError)
    assert "unbound" in issue.message
    assert issue.declaration == "Selected"


def test_uncovered_subject_member_rejects_the_whole_alternative_map(
    tmp_path: Path,
) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Selected():\n"
        '    Item = Capture("Item")\n'
        "    return Map[list[int] | set[str], list[Item] | tuple[Item, ...]: Item]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    with pytest.raises(PydanticSchemaGenerationError, match="no_match"):
        TypeAdapter(Schema[namespace["Selected"]])

    source = tmp_path / "uncovered.py"
    source.write_text(program)
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    assert "no case matched" in result.failure().message


def test_alias_alternatives_keep_the_enclosing_parameter_argument(
    tmp_path: Path,
) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "type Choices[A] = list[A] | tuple[A, ...]\n"
        "@type_function\n"
        "def Selected[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[T, Choices[Item]: tuple[Item, T], ...: bytes]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    specialized: object = eval("Selected[list[int] | tuple[str, ...]]", namespace)
    expected = (
        "tuple[int, list[int] | tuple[str, ...]] | "
        "tuple[str, list[int] | tuple[str, ...]]"
    )
    expected_type: object = eval(expected, namespace)
    assert (
        TypeAdapter(Schema[specialized]).json_schema()
        == TypeAdapter(expected_type).json_schema()
    )
    source = tmp_path / "aliases.py"
    source.write_text(
        program + "class Payload:\n    value: Selected[list[int] | tuple[str, ...]]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert generated.content.endswith(f"class Payload:\n    value: {expected}\n")


def test_separate_map_branches_keep_ordered_priority(tmp_path: Path) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Repeated[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[T, tuple[Item, str]: tuple[Item, Item], "
        "tuple[int, Item]: tuple[Item, Item], ...: bytes]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    specialized: object = eval("Repeated[tuple[int, str]]", namespace)
    assert (
        TypeAdapter(Schema[specialized]).json_schema()
        == TypeAdapter(tuple[int, int]).json_schema()
    )
    source = tmp_path / "priority.py"
    source.write_text(
        program + "class Payload:\n    value: Repeated[tuple[int, str]]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert generated.content.endswith("class Payload:\n    value: tuple[int, int]\n")


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_alternative_outputs_remain_correlated_in_checker_projection(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "alternatives.py"
    source.write_text(
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Repeated[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[T, tuple[Item, str] | tuple[int, Item]: "
        "tuple[Item, Item], ...: bytes]\n"
        "class Payload:\n"
        "    value: Repeated[tuple[int, str]]\n"
        "    fallback: Repeated[float]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "type Repeated[T] = object" in generated.content
    source.with_suffix(".pyi").write_text(generated.content)
    (tmp_path / "pyrefly.toml").write_text(
        'python-version = "3.14"\nsearch-path = ["."]\n'
    )
    (tmp_path / "pyrightconfig.json").write_text(
        '{"pythonVersion": "3.14", "typeCheckingMode": "strict"}'
    )
    consumer = tmp_path / "consumer.py"
    good = (
        "from typing import assert_type\n"
        "from alternatives import Payload\n"
        "def check(value: Payload) -> None:\n"
        "    assert_type(value.value, tuple[int, int] | tuple[str, str])\n"
        "    assert_type(value.fallback, bytes)\n"
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
        + "    return value.value\n"
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
