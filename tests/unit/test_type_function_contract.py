"""Reusable type-function construction through the production entry points."""

from pathlib import Path
from subprocess import run
from sys import executable
from typing import Annotated, TypeAliasType, TypeVar

import pytest
from returns.result import Failure

from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from typeforge import Map, TypeFunctionConstructionError, type_function
from typeforge.compiler.pipeline import generate_module
from typeforge.pydantic import Schema


def test_type_function_constructs_once_and_specializes_without_source() -> None:
    constructions: list[str] = []

    @type_function
    def Selected[T]():
        constructions.append("constructed")
        return Map[T, int:str, ...:bytes]

    assert isinstance(Selected, TypeAliasType)
    assert Selected.__module__ == __name__
    assert constructions == ["constructed"]
    assert TypeAdapter(Schema[Selected[int]]).json_schema() == {"type": "string"}
    assert TypeAdapter(Schema[Selected[str]]).json_schema() == {
        "type": "string",
        "format": "binary",
    }
    assert constructions == ["constructed"]
    with pytest.raises(AttributeError):
        Selected.__value__ = str


def test_supported_type_function_has_compiler_runtime_parity(tmp_path: Path) -> None:
    source = tmp_path / "functions.py"
    source.write_text(
        "from typeforge import Map, type_function\n"
        "from typeforge.pydantic import Schema\n"
        "@type_function\n"
        "def Selected[T]():\n"
        "    return Map[T, int: str, ...: bytes]\n"
        "class Payload:\n"
        "    text: Schema[Selected[int]]\n"
        "    binary: Schema[Selected[str]]\n"
    )

    generated = generate_module(source, maximum_arity=1).unwrap()

    assert "type Selected[T] = str | bytes" in generated.content
    assert "def Selected" not in generated.content
    assert generated.content.endswith(
        "class Payload:\n    text: str\n    binary: bytes\n"
    )


def test_compiler_rejects_body_without_executing_it(tmp_path: Path) -> None:
    sentinel = tmp_path / "executed.txt"
    source = tmp_path / "unsupported.py"
    source.write_text(
        "from pathlib import Path\n"
        "from typeforge import type_function\n"
        "@type_function\n"
        "def Bad[T]():\n"
        f"    Path({str(sentinel)!r}).write_text('bad')\n"
        "    return T\n"
    )

    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    assert "type_function" in result.failure().message
    assert not sentinel.exists()


@pytest.mark.parametrize(
    ("definitions", "expression", "expected"),
    [
        ("def Identity[T]():\n    return T", "Identity[int]", "int"),
        ("def Items[T]():\n    return list[T]", "Items[int]", "list[int]"),
        ("def Constant():\n    return bytes", "Constant", "bytes"),
        ("def Identity[Selected]():\n    return Selected", "Identity[int]", "int"),
        ("def Identity[Map]():\n    return Map", "Identity[int]", "int"),
        (
            "def Exact[T]():\n    return Map[T, Is[int | str]: bytes, ...: str]",
            "Exact[str | int]",
            "bytes",
        ),
        (
            "def Items[T]():\n    return list[Selected[T]]",
            "Items[int]",
            "list[str]",
        ),
    ],
)
def test_type_function_composition_and_plain_annotations(
    tmp_path: Path, definitions: str, expression: str, expected: str
) -> None:
    imports = (
        "from typeforge import Is, Map, type_function\n"
        "from typeforge.pydantic import Schema\n"
    )
    program = (
        imports
        + "@type_function\ndef Selected[T]():\n"
        + "    return Map[T, int: str, ...: bytes]\n"
        + "@type_function\n"
        + definitions
        + "\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    annotation: object = eval(expression, namespace)
    expected_type: object = eval(expected, namespace)
    assert (
        TypeAdapter(Schema[annotation]).json_schema()
        == TypeAdapter(expected_type).json_schema()
    )
    source = tmp_path / "composed.py"
    source.write_text(
        program
        + f"type Result = {expression}\nclass Payload:\n    value: {expression}\n"
    )

    generated = generate_module(source, maximum_arity=1).unwrap()

    assert f"type Result = {expected}" in generated.content
    assert generated.content.endswith(f"class Payload:\n    value: {expected}\n")


@pytest.mark.parametrize(
    "declaration",
    [
        "def Bad[T]():\n    if T:\n        return str\n    return int",
        "def Bad[T]():\n    return helper(T)",
        "def Bad[T]():\n    return T if T else str",
        "def Bad[T]():\n    return 42",
        "def Bad[T]():\n    return",
        "def Bad[T](value):\n    return T",
        "async def Bad[T]():\n    return T",
        "def Bad[*Ts]():\n    return tuple[*Ts]",
        "def Bad[T: int]():\n    return T",
        "def Bad[T = int]():\n    return T",
    ],
)
def test_unsupported_type_function_source_is_an_authored_failure(
    tmp_path: Path, declaration: str
) -> None:
    source = tmp_path / "bad.py"
    source.write_text(
        "from typeforge import type_function\n@type_function\n" + declaration
    )

    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    assert "type_function" in result.failure().message
    assert result.failure().path == source


def test_type_function_alias_recursion_uses_the_existing_failure_boundary(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recursive.py"
    source.write_text(
        "from typeforge import type_function\n@type_function\n"
        "def Cycle[T]():\n    return Cycle[T]\n"
    )

    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    assert "cyclic schema alias" in result.failure().message
    assert result.failure().expression == "Cycle[T]"


def test_runtime_validates_the_template_and_preserves_body_failures() -> None:
    def invalid():
        return {"mutable": str}

    with pytest.raises(TypeFunctionConstructionError, match="must return a type"):
        type_function(invalid)

    failure = RuntimeError("construction failed")

    def broken():
        raise failure

    with pytest.raises(RuntimeError) as caught:
        type_function(broken)

    assert caught.value is failure


def test_runtime_model_specialization_and_rebuild_do_not_replay_the_body() -> None:
    constructions: list[str] = []

    @type_function
    def Selected[T]():
        constructions.append("constructed")
        return Map[T, int:str, ...:bytes]

    class Model[T](BaseModel):
        value: Schema[Selected[T]]

    assert Model[int](value="text").value == "text"
    assert Model[str](value=b"binary").value == b"binary"
    Model[int].model_rebuild(force=True)
    Model[str].model_rebuild(force=True)
    assert constructions == ["constructed"]


def test_runtime_metadata_is_opaque_during_template_construction() -> None:
    @type_function
    def Items[T]():
        return Annotated[list[T], Field(min_length=1)]

    adapter = TypeAdapter(Schema[Items[int]])
    assert adapter.validate_python(["1"]) == [1]
    with pytest.raises(ValidationError):
        adapter.validate_python([])


def test_template_parameters_must_belong_to_the_function() -> None:
    External = TypeVar("External")

    with pytest.raises(TypeFunctionConstructionError, match="unbound type parameter"):

        @type_function
        def Bad[T]():
            return list[External]


def test_construction_leaves_unrelated_closure_cells_lazy() -> None:
    @type_function
    def Items[T]():
        if len([]):
            return later

        return list[T]

    later = str
    assert TypeAdapter(Schema[Items[int]]).validate_python(["1"]) == [1]


def test_unrelated_same_named_parameters_keep_their_identity() -> None:
    @type_function
    def Items[T]():
        return list[T]

    @type_function
    def Pairs[T]():
        return tuple[Items[T], T]

    assert Items.__type_params__[0] is not Pairs.__type_params__[0]
    assert TypeAdapter(Schema[Pairs[str]]).validate_python((["a"], "b")) == (
        ["a"],
        "b",
    )


def test_symbolic_parameter_truthiness_fails_during_construction() -> None:
    with pytest.raises(TypeFunctionConstructionError, match="truthiness"):

        @type_function
        def Bad[T]():
            return str if T else bytes


def test_symbolic_map_truthiness_fails_during_construction() -> None:
    with pytest.raises(TypeError, match="truthiness"):

        @type_function
        def Bad[T]():
            selected = Map[T, int:str, ...:bytes]
            return str if selected else bytes


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_existing_checkers_consume_type_function_outputs(
    tmp_path: Path, checker: str
) -> None:
    library = tmp_path / "library.py"
    library.write_text(
        "from typeforge import Map, type_function\n"
        "@type_function\ndef Selected[T]():\n"
        "    return Map[T, int: str, ...: bytes]\n"
        "@type_function\ndef Items[T]():\n    return list[T]\n"
        "class Payload:\n"
        "    text: Selected[int]\n    values: Items[int]\n"
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
    program = (
        "from typing import assert_type\nfrom library import Payload\n"
        "def verify(value: Payload) -> None:\n"
        "    assert_type(value.text, str)\n"
        "    assert_type(value.values, list[int])\n"
    )
    consumer.write_text(program)
    accepted = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    consumer.write_text(program + "    wrong: bytes = value.text\n    print(wrong)\n")
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "str" in rejected.stdout + rejected.stderr
