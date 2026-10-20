"""Bare generic compatibility and its explicit supported frontier."""

from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from returns.result import Failure

from pydantic import PydanticSchemaGenerationError, TypeAdapter
from typeforge.compiler.pipeline import generate_module
from typeforge.pydantic import Schema


@pytest.mark.parametrize(
    ("subject", "selector", "expected"),
    [
        ("list[bool]", "list[int]", "bytes"),
        ("Sequence[bool]", "Sequence[int]", "str"),
        ("list[bool]", "Sequence[int]", "str"),
        ("tuple[bool, str]", "Sequence[int | str]", "str"),
        ("list[int]", "list[Any]", "str"),
        ("list[Any]", "list[int]", "str"),
        ("dict[str, bool]", "dict[str, int]", "bytes"),
        ("dict[str, bool]", "Mapping[str, int]", "str"),
        ("frozenset[bool]", "frozenset[int]", "str"),
        ("Sequence[bool]", "Is[Sequence[int]]", "bytes"),
        ("Sequence[int]", "Is[Seq[int]]", "str"),
        ("list[Sequence[bool]]", "list[Sequence[int]]", "bytes"),
        ("Sequence[list[bool]]", "Sequence[list[int]]", "bytes"),
        ("Seq[bool]", "Sequence[int]", "str"),
        ("Box[int]", "Box[int]", "str"),
        ("Sequence[Literal[True]]", "Sequence[int]", "str"),
        ("tuple[()]", "Sequence[int]", "str"),
        ("list[int]", "Any", "str"),
    ],
)
def test_fixed_generic_selection_matches_in_both_consumers(
    tmp_path: Path, subject: str, selector: str, expected: str
) -> None:
    imports = (
        "from collections.abc import Mapping, Sequence\n"
        "from collections.abc import Sequence as Seq\n"
        "from typing import Any, Literal\n"
        "from typeforge import Is, Map\n"
        "from typeforge.pydantic import Schema\n"
        "class Box[T]: ...\n"
    )
    expression = f"Map[{subject}, {selector}: str, ...: bytes]"
    namespace: dict[str, object] = {"__name__": __name__}
    exec(imports, namespace)
    annotation: object = eval(expression, namespace)
    result_type: object = eval(expected, namespace)
    assert (
        TypeAdapter(Schema[annotation]).json_schema()
        == TypeAdapter(result_type).json_schema()
    )
    source = tmp_path / "generic.py"
    source.write_text(
        imports + "class Payload:\n" + f"    value: Schema[{expression}]\n"
    )

    generated = generate_module(source, maximum_arity=1).unwrap()

    assert generated.content.endswith(f"class Payload:\n    value: {expected}\n")


def test_unknown_generic_variance_does_not_silently_choose_fallback(
    tmp_path: Path,
) -> None:
    imports = (
        "from typeforge import Map\n"
        "from typeforge.pydantic import Schema\n"
        "class Box[T]: ...\n"
    )
    expression = "Map[Box[int], Box[object]: str, ...: bytes]"
    namespace: dict[str, object] = {"__name__": __name__}
    exec(imports, namespace)
    annotation: object = eval(expression, namespace)
    with pytest.raises(
        PydanticSchemaGenerationError, match="supported generic compatibility"
    ):
        TypeAdapter(Schema[annotation])

    source = tmp_path / "unsupported.py"
    source.write_text(
        imports + "class Payload:\n" + f"    value: Schema[{expression}]\n"
    )
    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    assert "supported generic compatibility" in result.failure().message
    assert result.failure().expression == f"Schema[{expression}]"


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_generic_rules_and_generated_outputs_follow_checkers(
    tmp_path: Path, checker: str
) -> None:
    library = tmp_path / "generic_library.py"
    library.write_text(
        "from collections.abc import Sequence\n"
        "from typeforge import Map\n"
        "from typeforge.pydantic import Schema\n"
        "class Payload:\n"
        "    invariant: Schema[Map[list[bool], list[int]: str, ...: bytes]]\n"
        "    covariant: Schema[Map[Sequence[bool], Sequence[int]: str, ...: bytes]]\n"
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
        "from typing import Any, Literal, assert_type\n"
        "from collections.abc import Mapping, Sequence\n"
        "from generic_library import Payload\n"
        "def verify(value: Payload, flags: list[bool]) -> Sequence[int]:\n"
        "    assert_type(value.invariant, bytes)\n"
        "    assert_type(value.covariant, str)\n"
        "    return flags\n"
        "def mapping(values: dict[str, bool]) -> Mapping[str, int]:\n"
        "    return values\n"
        "def immutable(values: frozenset[bool]) -> frozenset[int]:\n"
        "    return values\n"
        "def elements(values: tuple[bool, str]) -> Sequence[int | str]:\n"
        "    return values\n"
        "def gradual(values: list[Any]) -> list[int]:\n"
        "    return values\n"
        "def literals(values: Sequence[Literal[True]]) -> Sequence[int]:\n"
        "    return values\n"
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
        good
        + "def reject(value: Payload, flags: list[bool]) -> list[int]:\n"
        + "    invalid: str = value.invariant\n"
        + "    print(invalid)\n"
        + "    return flags\n"
        + "def reject_mapping(values: dict[str, bool]) -> dict[str, int]:\n"
        + "    return values\n"
    )
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "bytes" in rejected.stdout + rejected.stderr
    assert "bool" in rejected.stdout + rejected.stderr
