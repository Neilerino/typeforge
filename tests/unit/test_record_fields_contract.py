"""Record construction through the public compiler and runtime boundaries."""

from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from returns.result import Failure

from pydantic import TypeAdapter, ValidationError
from typeforge.compiler.pipeline import generate_module
from typeforge.pydantic import Schema

_PUBLIC = (
    "from typing import Literal, NotRequired, ReadOnly, TypedDict\n"
    "from typeforge import Drop, Fields, Map, Record, type_function\n"
    "class User(TypedDict):\n"
    "    password: str\n"
    "    name: ReadOnly[str]\n"
    "    age: NotRequired[int]\n"
    "@type_function\n"
    "def Public[T]():\n"
    "    return Record(\n"
    "        Map[field.name, Literal['password']: Drop, ...: field]\n"
    "        for field in Fields[T]\n"
    "    )\n"
)


def test_record_fields_preserves_passed_through_fields_without_source() -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(_PUBLIC, namespace)
    selected: object = eval("Public[User]", namespace)

    adapter = TypeAdapter(Schema[selected])

    assert adapter.validate_python({"name": "Ada", "age": "2"}) == {
        "name": "Ada",
        "age": 2,
    }
    assert adapter.validate_python({"name": "Ada", "password": "secret"}) == {
        "name": "Ada"
    }
    schema = adapter.json_schema()
    assert schema["required"] == ["name"]
    assert set(schema["properties"]) == {"name", "age"}
    assert schema["properties"]["name"]["readOnly"] is True


def test_compiler_materializes_record_fields_without_executing_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "records.py"
    source.write_text(_PUBLIC + "type PublicUser = Public[User]\n")

    generated = generate_module(source, maximum_arity=1).unwrap()

    assert "type Public[T] = object" in generated.content
    assert "class Public_User(tf_typing.TypedDict):" in generated.content
    public = generated.content.split("class Public_User", 1)[1].split("\n\n", 1)[0]
    assert "password:" not in public
    assert "name: tf_typing.ReadOnly[str]" in public
    assert "age: tf_typing.NotRequired[int]" in public
    assert "type PublicUser = Public_User" in generated.content


def test_record_fields_constructs_once_through_generic_models_and_rebuild() -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    program = (
        "from pydantic import BaseModel\n"
        "from typeforge.pydantic import Schema\n"
        "calls = []\n"
        + _PUBLIC.replace(
            "    return Record(", "    calls.append('built')\n    return Record("
        )
        + "class Payload[T](BaseModel):\n"
        "    value: Schema[Public[T]]\n"
        "class Other(TypedDict):\n    count: int\n"
        "assert calls == ['built']\n"
        "assert Payload[User](value={'name': 'Ada'}).model_dump() == "
        "{'value': {'name': 'Ada'}}\n"
        "assert Payload[Other](value={'count': '2'}).model_dump() == "
        "{'value': {'count': 2}}\n"
        "Payload[User].model_rebuild(force=True)\n"
        "Payload[Other].model_rebuild(force=True)\n"
        "assert calls == ['built']\n"
    )
    exec(program, namespace)
    with pytest.raises(ValidationError, match="typeforge_unsupported_record"):
        exec("Payload(value={'invented': 1})", namespace)


def test_record_passthrough_preserves_leaf_metadata() -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(
        "from typing import Annotated, TypedDict\n"
        "from pydantic import Field\n"
        "from typeforge import Record, Fields, type_function\n"
        "class Row(TypedDict):\n    count: Annotated[int, Field(gt=0)]\n"
        "@type_function\ndef Copy[T]():\n"
        "    return Record(field for field in Fields[T])\n",
        namespace,
    )
    selected: object = eval("Copy[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({"count": "2"}) == {"count": 2}
    assert adapter.json_schema()["properties"]["count"]["exclusiveMinimum"] == 0
    with pytest.raises(ValidationError):
        adapter.validate_python({"count": 0})


def test_record_all_drop_retains_source_type_parameters() -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(
        "from typeforge import Record, Fields, Drop, type_function\n"
        "from typing import TypedDict\n"
        "class Row(TypedDict):\n    value: int\n"
        "@type_function\ndef Empty[T]():\n"
        "    return Record(Drop for field in Fields[T])\n"
        "assert Empty.__value__.__parameters__ == Empty.__type_params__\n",
        namespace,
    )
    selected: object = eval("Empty[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({"value": "3"}) == {}
    assert adapter.json_schema()["properties"] == {}


@pytest.mark.parametrize(
    "expression",
    [
        "Record(field for field in Fields[T] if field.name)",
        "Record(field for field in Fields[T] for other in Fields[T])",
        "Record(field for field, other in Fields[T])",
        "Record([field for field in Fields[T]])",
        "Record(field for field in list[T])",
        "Record(field.unknown for field in Fields[T])",
        "Record(helper(field) for field in Fields[T])",
    ],
)
def test_compiler_rejects_unsupported_record_construction_at_authored_source(
    tmp_path: Path, expression: str
) -> None:
    source = tmp_path / "unsupported.py"
    source.write_text(
        "from typeforge import Record, Fields, type_function\n"
        "@type_function\ndef Bad[T]():\n"
        f"    return {expression}\n"
    )

    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    assert result.failure().path == source
    assert "Record" in result.failure().message or "field" in result.failure().message


def test_record_construction_resets_scope_after_an_unexpected_failure() -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(_PUBLIC, namespace)
    failure = RuntimeError("construction failed")
    namespace["failure"] = failure

    with pytest.raises(RuntimeError) as caught:
        exec(
            "def broken():\n"
            "    for field in Fields[User]:\n"
            "        raise failure\n"
            "        yield field\n"
            "Record(broken())\n",
            namespace,
        )

    assert caught.value is failure
    with pytest.raises(TypeError, match="consumed by Record"):
        exec("list(Fields[User])", namespace)

    selected: object = eval("Record(field for field in Fields[User])", namespace)
    assert TypeAdapter(Schema[selected]).validate_python(
        {"password": "secret", "name": "Ada"}
    ) == {"password": "secret", "name": "Ada"}


@pytest.mark.parametrize(
    "expression",
    [
        "Record(field for field in Fields[User] if False)",
        "Record(field for field in Fields[User] for other in Fields[User])",
        "Record(())",
    ],
)
def test_runtime_rejects_malformed_record_construction(expression: str) -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(_PUBLIC, namespace)
    with pytest.raises(TypeError, match="Fields iteration"):
        eval(expression, namespace)


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_existing_checkers_consume_record_type_function_output(
    tmp_path: Path, checker: str
) -> None:
    library = tmp_path / "library.py"
    library.write_text(_PUBLIC + "type PublicUser = Public[User]\n")
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
        "from typing import assert_type\nfrom library import PublicUser\n"
        "def verify(value: PublicUser) -> None:\n"
        "    assert_type(value['name'], str)\n"
        "    if 'age' in value:\n"
        "        assert_type(value['age'], int)\n"
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

    consumer.write_text(
        program + "    wrong: bytes = value['name']\n    print(wrong)\n"
    )
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "str" in rejected.stdout + rejected.stderr
