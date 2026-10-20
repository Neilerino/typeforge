"""Lexical aliases and composition through both production frontends."""

from pathlib import Path
from subprocess import run
from sys import executable
from typing import TypeAliasType, get_origin

import pytest
from pydantic.errors import PydanticSchemaGenerationError
from returns.result import Failure

from pydantic import BaseModel, TypeAdapter
from typeforge import Map, type_function
from typeforge.compiler.adaptation import AdaptationError
from typeforge.compiler.pipeline import generate_module
from typeforge.compiler.source import parse_source
from typeforge.pydantic import Schema

_SCALAR = (
    "from typeforge import Map, type_function\n"
    "@type_function\ndef Selected[T]():\n"
    "    type Local[A] = Map[A, int: str, ...: bytes]\n"
    "    return list[Local[T]]\n"
)


def test_local_generic_alias_specializes_through_runtime_and_compiler(
    tmp_path: Path,
) -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(_SCALAR, namespace)
    selected: object = eval("Selected[int]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python(["text"]) == ["text"]
    assert adapter.json_schema()["items"] == {"type": "string"}

    source = tmp_path / "aliases.py"
    source.write_text(_SCALAR + "type Result = Selected[int]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "type Result = list[str]" in generated.content
    assert "type Local" not in generated.content


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("type Local = T\n    return Local", "int"),
        ("type Local[A] = tuple[T, A]\n    return Local[str]", "tuple[int, str]"),
        ("type Local[T] = list[T]\n    return Local[str]", "list[str]"),
        (
            "type Local[A, B] = dict[A, list[B]]\n    return Local[str, T]",
            "dict[str, list[int]]",
        ),
        (
            "type First[A] = Second[A]\n"
            "    type Second[A] = list[A]\n"
            "    return First[T]",
            "list[int]",
        ),
        (
            "type Local[A] = A\n    return Local[Local[T]]",
            "int",
        ),
        (
            "type Map[A] = list[A]\n    return Map[T]",
            "list[int]",
        ),
        (
            "A = Capture('A')\n    type Local[A] = list[A]\n    return Local[T]",
            "list[int]",
        ),
        (
            "A = Capture('element')\n"
            "    type Local[S] = Map[S, list[A]: tuple[A, A], ...: bytes]\n"
            "    return Local[list[T]]",
            "tuple[int, int]",
        ),
    ],
)
def test_local_alias_scope_and_composition(
    tmp_path: Path, body: str, expected: str
) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "type Local[A] = bytes\n"
        "@type_function\ndef Selected[T]():\n    " + body + "\n"
        "@type_function\ndef Independent[T]():\n"
        "    type Local[A] = set[A]\n    return Local[T]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Selected[int]", namespace)
    expected_type: object = eval(expected, namespace)
    assert (
        TypeAdapter(Schema[selected]).json_schema()
        == TypeAdapter(expected_type).json_schema()
    )
    independent: object = eval("Independent[str]", namespace)
    assert (
        TypeAdapter(Schema[independent]).json_schema()
        == TypeAdapter(set[str]).json_schema()
    )

    source = tmp_path / "scope.py"
    source.write_text(
        program + "type Result = Selected[int]\n" + "type Other = Independent[str]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert f"type Result = {expected}" in generated.content
    assert "type Other = set[str]" in generated.content
    assert "    type Local" not in generated.content


_RECORD = (
    "from typing import Literal, NotRequired, ReadOnly, TypedDict\n"
    "from typeforge import Drop, Fields, Map, Record, type_function\n"
    "class Row(TypedDict):\n"
    "    count: int\n"
    "    label: NotRequired[ReadOnly[str]]\n"
    "    password: str\n"
    "@type_function\ndef Public[T]():\n"
    "    return Record(\n"
    "        Map[field.name, Literal['password']: Drop, ...: field]\n"
    "        for field in Fields[T]\n"
    "    )\n"
    "@type_function\ndef WithoutIntegers[T]():\n"
    "    type DropCondition[A] = Map[A, int: Drop, ...: A]\n"
    "    type Visible = Public[T]\n"
    "    return Record(\n"
    "        field.replace(type=DropCondition[field.type])\n"
    "        for field in Fields[Visible]\n"
    "    )\n"
)


def test_local_generic_aliases_compose_record_operands_and_field_edits(
    tmp_path: Path,
) -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(_RECORD, namespace)
    selected: object = eval("WithoutIntegers[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({"label": "text", "password": "secret"}) == {
        "label": "text"
    }
    assert adapter.validate_python({}) == {}
    assert list(adapter.json_schema()["properties"]) == ["label"]
    assert adapter.json_schema()["properties"]["label"]["readOnly"] is True

    source = tmp_path / "composed_records.py"
    source.write_text(_RECORD + "type Result = WithoutIntegers[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "type Result = WithoutIntegers_Row" in generated.content
    result = generated.content.split("class WithoutIntegers_Row", 1)[1].split(
        "\n\n", 1
    )[0]
    assert "label: tf_typing.NotRequired[tf_typing.ReadOnly[str]]" in result
    assert "count:" not in result and "password:" not in result
    assert "DropCondition" not in generated.content
    assert (
        generated.content == generate_module(source, maximum_arity=1).unwrap().content
    )


def test_returning_a_composed_record_uses_the_existing_record_family(
    tmp_path: Path,
) -> None:
    program = (
        _RECORD
        + "@type_function\ndef Copy[T]():\n"
        + "    type Visible = Public[T]\n    return Visible\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Copy[Row]", namespace)
    assert TypeAdapter(Schema[selected]).validate_python({"count": "1"}) == {"count": 1}
    source = tmp_path / "copy.py"
    source.write_text(program + "type Result = Copy[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "type Result = Copy_Row" in generated.content
    result = generated.content.split("class Copy_Row", 1)[1].split("\n\n", 1)[0]
    assert "count: int" in result and "password:" not in result


def test_composition_keeps_callee_globals_distinct_from_caller_parameters(
    tmp_path: Path,
) -> None:
    program = (
        "from typeforge import type_function\n"
        "type T = bytes\n"
        "@type_function\ndef Other[S]():\n"
        "    type Local[A] = tuple[T, A]\n    return Local[S]\n"
        "@type_function\ndef Selected[T]():\n"
        "    type Local[A] = Other[A]\n    return Local[T]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Selected[int]", namespace)
    assert TypeAdapter(Schema[selected]).validate_python((b"text", "1")) == (b"text", 1)
    source = tmp_path / "callee_scope.py"
    source.write_text(program + "type Result = Selected[int]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "type Result = tuple[bytes, int]" in generated.content


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("type Local[A] = A\n    return Local", "requires 1 type argument"),
        ("type Local[A] = A\n    return Local[T, str]", "received 2"),
        ("type Local[A] = Local[A]\n    return Local[T]", "cyclic schema alias"),
        (
            "type First[A] = Second[A]\n"
            "    type Second[A] = First[A]\n    return First[T]",
            "cyclic schema alias",
        ),
        ("type Local[A] = helper(A)\n    return Local[T]", "construction"),
        ("type Local[*Ts] = tuple[*Ts]\n    return Local[T]", "ordinary"),
        ("type Local[A: int] = A\n    return Local[T]", "unconstrained"),
        ("type Local[A = int] = A\n    return Local[T]", "without defaults"),
        ("type Local = T\n    type Local = str\n    return Local", "more than once"),
        (
            "A = Capture('A')\n    type A = T\n    return A",
            "more than once",
        ),
    ],
)
def test_unsupported_local_aliases_fail_at_the_authored_boundary(
    tmp_path: Path, body: str, message: str
) -> None:
    source = tmp_path / "bad_alias.py"
    source.write_text(
        "from typeforge import Capture, type_function\n"
        "@type_function\ndef Selected[T]():\n    " + body + "\n"
    )
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    error = result.failure()
    if isinstance(error, AdaptationError):
        assert error.declaration == "Selected"
        assert "Local" in error.expression or "First" in error.expression
    else:
        assert error.path == source

    assert message in error.message


def test_runtime_nested_alias_parameters_remain_unbound_without_application() -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(
        "from typeforge import Map, type_function\n"
        "@type_function\ndef Selected[T]():\n"
        "    type Local[A] = Map[A, int: str, ...: bytes]\n"
        "    return Local\n",
        namespace,
    )
    selected: object = eval("Selected[int]", namespace)
    origin = get_origin(selected)
    assert isinstance(origin, TypeAliasType)
    local = origin.__value__
    assert isinstance(local, TypeAliasType)
    assert len(local.__type_params__) == 1
    assert local.__type_params__[0] is not origin.__type_params__[0]
    assert get_origin(local) is None


def test_runtime_local_alias_rebuild_does_not_replay_construction() -> None:
    constructions: list[str] = []

    @type_function
    def Selected[T]():
        constructions.append("constructed")
        type Local[A] = Map[A, int:str, ...:bytes]
        return list[Local[T]]

    class Model[T](BaseModel):
        value: Schema[Selected[T]]

    assert Model[int](value=["text"]).value == ["text"]
    assert Model[str](value=[b"binary"]).value == [b"binary"]
    Model[int].model_rebuild(force=True)
    Model[str].model_rebuild(force=True)
    assert constructions == ["constructed"]


def test_source_retains_local_alias_origins_and_capture_identity() -> None:
    source = (
        parse_source(
            "from typeforge import Capture, Map, type_function\n"
            "@type_function\ndef Selected[T]():\n"
            "    A = Capture('element')\n"
            "    type Local[S] = Map[S, list[A]: A, ...: bytes]\n"
            "    return Local[T]\n",
            Path("authored.py"),
        )
        .unwrap()
        .source
    )
    function = source.aliases[0]
    local = function.local_aliases[0]
    assert local.qualified_name == ("Selected", "Local")
    assert local.span.start.line == 5
    assert local.value.span.start.line == 5
    assert len(source.aliases) == 1


def test_local_alias_substitution_preserves_distinct_capture_declarations(
    tmp_path: Path,
) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\ndef Selected[T]():\n"
        "    A = Capture('element')\n"
        "    B = Capture('element')\n"
        "    type Local[S] = Map[S, list[A]: tuple[A, B], ...: bytes]\n"
        "    return Local[T]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Selected[list[int]]", namespace)
    with pytest.raises(PydanticSchemaGenerationError, match="unbound_capture"):
        TypeAdapter(Schema[selected])

    source = tmp_path / "distinct_captures.py"
    source.write_text(program + "type Result = Selected[list[int]]\n")
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, AdaptationError)
    assert error.declaration == "Result"
    assert "unbound" in error.message


@pytest.mark.parametrize(
    ("definition", "application", "message"),
    [
        ("type Local[A] = A", "Local[T, str]", "Too many arguments"),
        ("type Local[A, B] = A", "Local[T]", "Not enough arguments"),
        (
            "type Local[A] = Map[A, int: str, ...: Local[A]]",
            "Local[T]",
            "alias_cycle",
        ),
    ],
)
def test_runtime_local_alias_failures_use_the_existing_schema_boundary(
    definition: str, application: str, message: str
) -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(
        "from typeforge import Map, type_function\n"
        "@type_function\ndef Selected[T]():\n    "
        + definition
        + "\n    return "
        + application
        + "\n",
        namespace,
    )
    selected: object = eval("Selected[int]", namespace)
    with pytest.raises(PydanticSchemaGenerationError, match=message):
        TypeAdapter(Schema[selected])


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_checkers_enforce_local_alias_and_composed_record_results(
    tmp_path: Path, checker: str
) -> None:
    library = tmp_path / "library.py"
    library.write_text(
        _SCALAR
        + _RECORD
        + "type Items = Selected[int]\n"
        + "type Result = WithoutIntegers[Row]\n"
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
        "from typing import assert_type\nfrom library import Items, Result\n"
        "items: Items = ['text']\nempty: Result = {}\n"
        "def check(value: Result) -> None:\n"
        "    if 'label' in value:\n        assert_type(value['label'], str)\n"
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
    consumer.write_text(program + "    value['label'] = 'edited'\n")
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "label" in rejected.stdout + rejected.stderr
