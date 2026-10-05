"""Keyword field construction and immutable edits at production boundaries."""

from pathlib import Path
from subprocess import run
from sys import executable
from typing import get_args

import pytest
from pydantic.errors import PydanticSchemaGenerationError
from returns.result import Failure

import typeforge
from pydantic import TypeAdapter, ValidationError
from typeforge import Field
from typeforge.compiler.pipeline import generate_module
from typeforge.compiler.record_materialization import RecordMaterializationError
from typeforge.pydantic import Schema

_CONSTRUCTION = (
    "from typing import NotRequired, ReadOnly, TypedDict\n"
    "from typeforge import Field, Fields, Record, type_function\n"
    "class Row(TypedDict):\n"
    "    name: NotRequired[ReadOnly[str]]\n"
    "@type_function\ndef Changed[T]():\n"
    "    return Record(\n"
    "        Field(name='display_name', type=bytes, required=False, readonly=True)\n"
    "        for field in Fields[T]\n"
    "    )\n"
)


def test_runtime_constructs_field_with_keyword_data() -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(_CONSTRUCTION, namespace)
    selected: object = eval("Changed[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])

    assert adapter.validate_python({}) == {}
    assert adapter.validate_python({"display_name": "text"}) == {
        "display_name": b"text"
    }
    schema = adapter.json_schema()
    assert schema.get("required", []) == []
    assert schema["properties"]["display_name"]["readOnly"] is True


def test_compiler_constructs_field_with_keyword_data(tmp_path: Path) -> None:
    source = tmp_path / "fields.py"
    source.write_text(_CONSTRUCTION + "type Result = Changed[Row]\n")

    generated = generate_module(source, maximum_arity=1).unwrap()

    assert "class Changed_Row(tf_typing.TypedDict):" in generated.content
    assert (
        "display_name: tf_typing.NotRequired[tf_typing.ReadOnly[bytes]]"
        in generated.content
    )
    assert "type Result = Changed_Row" in generated.content


def test_runtime_replacement_preserves_unedited_flags() -> None:
    program = _CONSTRUCTION.replace(
        "Field(name='display_name', type=bytes, required=False, readonly=True)",
        "field.replace(type=bytes)",
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Changed[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])

    assert adapter.validate_python({}) == {}
    assert adapter.validate_python({"name": "text"}) == {"name": b"text"}
    assert adapter.json_schema()["properties"]["name"]["readOnly"] is True


def test_compiler_replacement_preserves_unedited_flags(tmp_path: Path) -> None:
    source = tmp_path / "edited.py"
    source.write_text(
        _CONSTRUCTION.replace(
            "Field(name='display_name', type=bytes, required=False, readonly=True)",
            "field.replace(type=bytes)",
        )
        + "type Result = Changed[Row]\n"
    )

    generated = generate_module(source, maximum_arity=1).unwrap()

    assert "name: tf_typing.NotRequired[tf_typing.ReadOnly[bytes]]" in generated.content


@pytest.mark.parametrize(
    ("edit", "name", "value", "expected"),
    [
        ("field.replace(name='title')", "title", "abc", "abc"),
        ("field.replace(type=int)", "name", "22", 22),
        ("field.replace(type=list[field.type])", "name", ["abc"], ["abc"]),
    ],
)
def test_replacement_uses_complete_annotation_at_its_original_position(
    edit: str, name: str, value: object, expected: object
) -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(
        "from typing import Annotated, NotRequired, ReadOnly, TypedDict\n"
        "from pydantic import Field as Constraint\n"
        "from typeforge import Record, Fields, type_function\n"
        "class Row(TypedDict):\n"
        "    name: NotRequired[ReadOnly[Annotated[str, Constraint(max_length=3)]]]\n"
        "@type_function\ndef Changed[T]():\n"
        f"    return Record({edit} for field in Fields[T])\n",
        namespace,
    )
    selected: object = eval("Changed[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({}) == {}
    assert adapter.validate_python({name: value}) == {name: expected}
    field = adapter.json_schema()["properties"][name]
    assert field["readOnly"] is True

    if "list[" in edit:
        assert field["type"] == "array"
        assert "maxLength" not in field
        assert field["items"]["maxLength"] == 3
        invalid: object = ["long"]
    elif "type=int" in edit:
        assert field["type"] == "integer"
        assert "maxLength" not in field
        invalid = "not an integer"
    else:
        assert field["maxLength"] == 3
        invalid = "long"

    with pytest.raises(ValidationError):
        adapter.validate_python({name: invalid})


def test_new_record_keeps_field_metadata_without_copying_record_metadata() -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(
        "from typing import Annotated, TypedDict\n"
        "from pydantic import Field as Constraint\n"
        "from typeforge import Record, Fields, type_function\n"
        "class Row(TypedDict):\n"
        "    name: Annotated[str, Constraint(max_length=3)]\n"
        "@type_function\ndef Tagged[T]():\n"
        "    return Annotated[\n"
        "        Record(field for field in Fields[T]),\n"
        "        Constraint(title='Tagged', json_schema_extra={'private': True}),\n"
        "    ]\n"
        "@type_function\ndef Copy[T]():\n"
        "    return Record(field for field in Fields[Tagged[T]])\n",
        namespace,
    )
    tagged: object = eval("Tagged[Row]", namespace)
    copied: object = eval("Copy[Row]", namespace)
    original_schema = TypeAdapter(Schema[tagged]).json_schema()
    copied_schema = TypeAdapter(Schema[copied]).json_schema()

    assert original_schema["title"] == "Tagged"
    assert original_schema["private"] is True
    assert copied_schema.get("title") != "Tagged"
    assert "private" not in copied_schema
    assert copied_schema["properties"]["name"]["maxLength"] == 3


def test_new_field_defaults_replace_source_modifiers(tmp_path: Path) -> None:
    program = _CONSTRUCTION.replace(
        "Field(name='display_name', type=bytes, required=False, readonly=True)",
        "Field(name=field.name, type=field.type)",
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Changed[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    schema = adapter.json_schema()
    assert schema["required"] == ["name"]
    assert "readOnly" not in schema["properties"]["name"]
    with pytest.raises(ValidationError):
        adapter.validate_python({})

    source = tmp_path / "defaults.py"
    source.write_text(program + "type Result = Changed[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    changed = generated.content.split("class Changed_Row", 1)[1].split("\n\n", 1)[0]
    assert "name: str" in changed
    assert "NotRequired" not in changed and "ReadOnly" not in changed


def test_replacement_drop_removes_the_field_in_both_frontends(tmp_path: Path) -> None:
    program = _CONSTRUCTION.replace(
        "from typeforge import Field,", "from typeforge import Drop, Field,"
    ).replace(
        "Field(name='display_name', type=bytes, required=False, readonly=True)",
        "field.replace(type=Drop)",
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Changed[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({"name": "ignored"}) == {}
    assert adapter.json_schema()["properties"] == {}

    source = tmp_path / "dropped.py"
    source.write_text(program + "type Result = Changed[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "class Changed_Row(tf_typing.TypedDict):\n    pass" in generated.content


def test_replacement_chains_preserve_field_data(tmp_path: Path) -> None:
    program = _CONSTRUCTION.replace(
        "Field(name='display_name', type=bytes, required=False, readonly=True)",
        "field.replace(type=bytes).replace(name='label', readonly=False)",
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Changed[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({}) == {}
    assert adapter.validate_python({"label": "text"}) == {"label": b"text"}
    assert "readOnly" not in adapter.json_schema()["properties"]["label"]

    source = tmp_path / "chained.py"
    source.write_text(program + "type Result = Changed[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "label: tf_typing.NotRequired[bytes]" in generated.content


def test_compiler_treats_annotation_metadata_as_opaque(tmp_path: Path) -> None:
    program = (
        _CONSTRUCTION.replace(
            "from typing import NotRequired,",
            "from typing import Annotated as Tagged, NotRequired,",
        )
        .replace(
            "class Row(TypedDict):",
            "def Metadata(value: int) -> object:\n"
            "    raise RuntimeError('must not execute authored metadata')\n"
            "class Row(TypedDict):",
        )
        .replace("type=bytes", "type=Tagged[bytes, Metadata(1)]")
    )
    source = tmp_path / "opaque_metadata.py"
    source.write_text(program + "type Result = Changed[Row]\n")

    generated = generate_module(source, maximum_arity=1).unwrap()

    assert (
        "display_name: tf_typing.NotRequired[tf_typing.ReadOnly[bytes]]"
        in generated.content
    )


def _edited_program(expression: str) -> str:
    return (
        _CONSTRUCTION.replace(
            "from typeforge import Field,", "from typeforge import Drop, Field,"
        )
        .replace(
            "from typing import NotRequired,",
            "from typing import Literal, NotRequired,",
        )
        .replace(
            "Field(name='display_name', type=bytes, required=False, readonly=True)",
            expression,
        )
    )


@pytest.mark.parametrize(
    ("expression", "issue"),
    [
        ("Field(name='', type=int)", "expected_field_name"),
        ("Field(name='bad-key', type=int)", "expected_field_name"),
        ("Field(name='class', type=int)", "expected_field_name"),
        ("Field(name=Drop, type=int)", "expected_field_name"),
        ("Field(name=Literal[1], type=int)", "expected_field_name"),
        ("Field(name='name', type=Drop)", "expected_type"),
        ("field.replace(name=None)", "expected_field_name"),
        ("field.replace(name=Drop)", "expected_field_name"),
        ("field.replace(name='bad-key', type=Drop)", "expected_field_name"),
    ],
)
def test_invalid_field_edits_fail_through_both_frontends(
    tmp_path: Path, expression: str, issue: str
) -> None:
    program = _edited_program(expression)
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Changed[Row]", namespace)
    with pytest.raises(PydanticSchemaGenerationError, match=issue):
        TypeAdapter(Schema[selected])

    source = tmp_path / "invalid.py"
    source.write_text(program + "type Result = Changed[Row]\n")
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, RecordMaterializationError)
    assert error.declaration == "Changed"
    assert expression in error.expression
    assert "field" in error.message


@pytest.mark.parametrize(
    "expression",
    [
        "Field('name', int)",
        "Field(name='name')",
        "Field(type=int)",
        "Field(name='name', type=int, required=1)",
        "Field(name='name', type=int, readonly=None)",
        "Field(name='name', type=int, required=Drop)",
        "field.replace(required=Drop)",
        "field.replace(readonly=None)",
        "field.replace(unknown=True)",
    ],
)
def test_invalid_field_construction_is_rejected(
    tmp_path: Path, expression: str
) -> None:
    program = _edited_program(expression)
    namespace: dict[str, object] = {"__name__": __name__}
    with pytest.raises(TypeError):
        exec(program, namespace)

    source = tmp_path / "malformed.py"
    source.write_text(program + "type Result = Changed[Row]\n")
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    assert result.failure().path == source
    assert (
        "Field" in result.failure().message or "modifiers" in result.failure().message
    )


def test_field_edits_do_not_mutate_the_original() -> None:
    original = Field(name="name", type=str, required=False, readonly=True)
    original_data = get_args(original)
    renamed = original.replace(name="label").replace(type=bytes, readonly=False)

    assert get_args(original) == original_data
    assert renamed.name != original.name
    assert renamed.type is bytes
    assert original.type is str
    with pytest.raises(AttributeError):
        original.name = "mutated"


def test_empty_replacement_and_explicit_none_are_distinct(tmp_path: Path) -> None:
    for expression, expected_type in (
        ("field.replace()", "str"),
        ("field.replace(type=None)", "None"),
    ):
        program = _edited_program(expression)
        namespace: dict[str, object] = {"__name__": __name__}
        exec(program, namespace)
        selected: object = eval("Changed[Row]", namespace)
        adapter = TypeAdapter(Schema[selected])
        expected: object = "text" if expected_type == "str" else None
        assert adapter.validate_python({"name": expected}) == {"name": expected}
        assert adapter.validate_python({}) == {}

        source = tmp_path / "none.py"
        source.write_text(program + "type Result = Changed[Row]\n")
        generated = generate_module(source, maximum_arity=1).unwrap()
        assert (
            f"name: tf_typing.NotRequired[tf_typing.ReadOnly[{expected_type}]]"
            in generated.content
        )


def test_equal_output_fields_still_collide(tmp_path: Path) -> None:
    program = _edited_program("field.replace(name='same', type=int)").replace(
        "    name: NotRequired[ReadOnly[str]]",
        "    name: str\n    other: str",
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Changed[Row]", namespace)
    with pytest.raises(PydanticSchemaGenerationError, match="duplicate_field"):
        TypeAdapter(Schema[selected])

    source = tmp_path / "collision.py"
    source.write_text(program + "type Result = Changed[Row]\n")
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    assert "same" in result.failure().message


@pytest.mark.parametrize(
    "expression",
    ["Field[str, int]", "OptionalField[str, int]", "ReadonlyField[str, int]"],
)
def test_superseded_field_authoring_is_removed(tmp_path: Path, expression: str) -> None:
    assert not hasattr(typeforge, "OptionalField")
    assert not hasattr(typeforge, "ReadonlyField")
    source = tmp_path / "old.py"
    source.write_text(
        "from typeforge import Field, OptionalField, ReadonlyField, Fields, Record\n"
        f"type Bad[T] = Record({expression} for field in Fields[T])\n"
    )
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    assert "keyword" in result.failure().message


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_checkers_enforce_edited_field_types_and_readonly_state(
    tmp_path: Path, checker: str
) -> None:
    library = tmp_path / "library.py"
    library.write_text(_CONSTRUCTION + "type Result = Changed[Row]\n")
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
        "from typing import assert_type\nfrom library import Result\n"
        "empty: Result = {}\n"
        "def check(value: Result) -> None:\n"
        "    if 'display_name' in value:\n"
        "        assert_type(value['display_name'], bytes)\n"
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
    consumer.write_text(program + "    value['display_name'] = b'edited'\n")
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "display_name" in rejected.stdout + rejected.stderr
