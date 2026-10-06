"""Correlated record-union behavior through the production consumers."""

from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from pydantic.errors import PydanticSchemaGenerationError
from returns.result import Failure

from pydantic import TypeAdapter, ValidationError
from typeforge.compiler.pipeline import generate_module
from typeforge.compiler.record_materialization import RecordMaterializationError
from typeforge.pydantic import Schema

_PROGRAM = (
    "from typing import Literal, TypedDict\n"
    "from typeforge import Drop, Fields, Map, Record, type_function\n"
    "class Left(TypedDict):\n"
    "    kind: Literal['left']\n    payload: int\n    left_only: bool\n"
    "    secret: str\n"
    "class Right(TypedDict):\n"
    "    kind: Literal['right']\n    payload: str\n    right_only: bytes\n"
    "    secret: bytes\n"
    "@type_function\ndef Public[T]():\n"
    "    return Record(\n"
    "        Map[field.name, Literal['secret']: Drop, ...: field]\n"
    "        for field in Fields[T]\n"
    "    )\n"
)


def test_record_union_transforms_complete_alternatives_without_mixing_fields(
    tmp_path: Path,
) -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(_PROGRAM, namespace)
    selected: object = eval("Public[Left | Right]", namespace)
    adapter = TypeAdapter(Schema[selected])
    for value in (
        {"kind": "left", "payload": 1, "left_only": True},
        {"kind": "right", "payload": "text", "right_only": b"data"},
    ):
        assert adapter.validate_python(value, strict=True) == value

    for invalid in (
        {"kind": "left", "payload": "wrong", "left_only": True},
        {"kind": "right", "payload": 1, "right_only": b"data"},
        {"kind": "left", "payload": 1, "right_only": b"data"},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid, strict=True)

    assert len(adapter.json_schema()["anyOf"]) == 2
    source = tmp_path / "record_union.py"
    source.write_text(_PROGRAM + "type Result = Public[Left | Right]\n")
    generated = generate_module(source, maximum_arity=1).unwrap().content
    assert "type Result = Public_Left | Public_Right" in generated
    for name in ("Public_Left", "Public_Right"):
        output = generated.split(f"class {name}", 1)[1].split("\n\n", 1)[0]
        assert "secret:" not in output


@pytest.mark.parametrize("operand", ["Left | int", "int | Left"])
def test_an_unsupported_alternative_fails_the_whole_record_application(
    tmp_path: Path, operand: str
) -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(_PROGRAM, namespace)
    selected: object = eval(f"Public[{operand}]", namespace)
    with pytest.raises(
        PydanticSchemaGenerationError, match="unsupported_record"
    ) as runtime:
        TypeAdapter(Schema[selected])

    assert "subject: int" in str(runtime.value)

    source = tmp_path / "unsupported.py"
    source.write_text(_PROGRAM + f"type Result = Public[{operand}]\n")
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, RecordMaterializationError)
    assert error.declaration == "Result"
    assert error.expression == f"Public[{operand}]"
    assert "int" in error.message


def test_record_distribution_preserves_the_original_generic_argument(
    tmp_path: Path,
) -> None:
    program = _PROGRAM + (
        "from typeforge import Is\n"
        "@type_function\ndef Tagged[T]():\n"
        "    return Record(\n"
        "        field.replace(type=Map[T, Is[Left | Right]: bytes, ...: field.type])\n"
        "        for field in Fields[T]\n"
        "    )\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Tagged[Left | Right]", namespace)
    adapter = TypeAdapter(Schema[selected])
    value = {"kind": b"k", "payload": b"p", "left_only": b"l", "secret": b"s"}
    assert adapter.validate_python(value, strict=True) == value
    source = tmp_path / "whole_subject.py"
    source.write_text(program + "type Result = Tagged[Left | Right]\n")
    generated = generate_module(source, maximum_arity=1).unwrap().content
    result = generated.split("type Result = ", 1)[1].split("\n", 1)[0]
    for name in result.split(" | "):
        output = generated.split(f"class {name}", 1)[1].split("\n\n", 1)[0]
        assert "payload: bytes" in output
        assert "kind: bytes" in output


@pytest.mark.parametrize(
    ("application", "names"),
    [
        ("Public[Choice]", ("Public_Left", "Public_Right")),
        ("Public[GenericChoice[Right]]", ("Public_Left", "Public_Right")),
        ("Visible[Right | Left]", ("Visible_Right", "Visible_Left")),
        ("Public[Left | Left]", ("Public_Left",)),
    ],
)
def test_aliases_composition_order_and_duplicate_record_members(
    tmp_path: Path, application: str, names: tuple[str, ...]
) -> None:
    program = _PROGRAM + (
        "type Choice = Left | Right\n"
        "type GenericChoice[A] = Left | A\n"
        "@type_function\ndef Visible[T]():\n"
        "    type Local = Public[T]\n"
        "    return Record(field for field in Fields[Local])\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval(application, namespace)
    adapter = TypeAdapter(Schema[selected])
    left = {"kind": "left", "payload": 1, "left_only": True}
    assert adapter.validate_python(left, strict=True) == left
    if len(names) > 1:
        right = {"kind": "right", "payload": "text", "right_only": b"data"}
        assert adapter.validate_python(right, strict=True) == right
        assert len(adapter.json_schema()["anyOf"]) == 2

    source = tmp_path / "composed.py"
    source.write_text(program + f"type Result = {application}\n")
    generated = generate_module(source, maximum_arity=1).unwrap().content
    assert f"type Result = {' | '.join(names)}" in generated
    assert generated == generate_module(source, maximum_arity=1).unwrap().content


def test_record_union_preserves_modifiers_and_field_metadata(tmp_path: Path) -> None:
    program = (
        "from typing import Annotated, Literal, NotRequired, ReadOnly, TypedDict\n"
        "from pydantic import Field as Constraint\n"
        "from typeforge import Fields, Record, type_function\n"
        "class Left(TypedDict):\n"
        "    kind: Literal['left']\n"
        "    label: NotRequired[ReadOnly[Annotated[str, Constraint(min_length=2)]]]\n"
        "class Right(TypedDict):\n"
        "    kind: Literal['right']\n"
        "    label: ReadOnly[Annotated[bytes, Constraint(min_length=3)]]\n"
        "@type_function\ndef Copy[T]():\n"
        "    return Record(field for field in Fields[T])\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Copy[Left | Right]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({"kind": "left"}, strict=True) == {"kind": "left"}
    right = {"kind": "right", "label": b"abc"}
    assert adapter.validate_python(right, strict=True) == right
    for invalid in (
        {"kind": "left", "label": "a"},
        {"kind": "right", "label": b"ab"},
        {"kind": "right"},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid, strict=True)

    alternatives = adapter.json_schema()["anyOf"]
    for alternative in alternatives:
        assert alternative["properties"]["label"]["readOnly"] is True

    source = tmp_path / "metadata.py"
    source.write_text(program + "type Result = Copy[Left | Right]\n")
    generated = generate_module(source, maximum_arity=1).unwrap().content
    # Published fields retain the existing base-type projection for metadata.
    assert "tf_typing.NotRequired[tf_typing.ReadOnly[str]]" in generated
    assert "tf_typing.ReadOnly[bytes]" in generated


def test_record_union_metadata_is_cleared_by_new_construction() -> None:
    program = _PROGRAM + (
        "from typing import Annotated\n"
        "from pydantic import Field as Constraint\n"
        "@type_function\ndef Tagged[T]():\n"
        "    return Annotated[Public[T], Constraint(title='Tagged',"
        " json_schema_extra={'private': True})]\n"
        "@type_function\ndef Copy[T]():\n"
        "    return Record(field for field in Fields[Tagged[T]])\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    tagged: object = eval("Tagged[Left | Right]", namespace)
    copied: object = eval("Copy[Left | Right]", namespace)
    tagged_schema = TypeAdapter(Schema[tagged]).json_schema()
    copied_schema = TypeAdapter(Schema[copied]).json_schema()
    assert tagged_schema["title"] == "Tagged"
    assert tagged_schema["private"] is True
    assert len(tagged_schema["anyOf"]) == len(copied_schema["anyOf"]) == 2
    assert "private" not in copied_schema
    assert all("private" not in member for member in tagged_schema["anyOf"])


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_existing_checkers_retain_record_union_correlations(
    tmp_path: Path, checker: str
) -> None:
    library = tmp_path / "library.py"
    library.write_text(_PROGRAM + "type Result = Public[Left | Right]\n")
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
    program = (
        "from typing import assert_type\nfrom library import Result\n"
        "left: Result = {'kind': 'left', 'payload': 1, 'left_only': True}\n"
        "right: Result = {'kind': 'right', 'payload': 's', 'right_only': b'b'}\n"
        "def check(value: Result) -> None:\n"
        "    if value['kind'] == 'left':\n"
        "        assert_type(value['payload'], int)\n"
        "        assert_type(value['left_only'], bool)\n"
        "    else:\n"
        "        assert_type(value['payload'], str)\n"
        "        assert_type(value['right_only'], bytes)\n"
    )
    consumer = tmp_path / "consumer.py"
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
        program + "bad: Result = {'kind': 'left', 'payload': 's', 'left_only': True}\n"
    )
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    diagnostic = rejected.stdout + rejected.stderr
    assert "payload" in diagnostic or "Public_Left" in diagnostic


def test_an_unsupported_operand_fails_without_any_visible_records(
    tmp_path: Path,
) -> None:
    program = (
        "from typeforge import Fields, Record, type_function\n"
        "@type_function\ndef Copy[T]():\n"
        "    return Record(field for field in Fields[T])\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Copy[int | str]", namespace)
    with pytest.raises(PydanticSchemaGenerationError, match="unsupported_record"):
        TypeAdapter(Schema[selected])

    source = tmp_path / "no_records.py"
    source.write_text(program + "type Result = Copy[int | str]\n")
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, RecordMaterializationError)
    assert error.declaration == "Result"
    assert error.expression == "Copy[int | str]"


def test_record_union_naming_preserves_source_identity_and_avoids_collisions(
    tmp_path: Path,
) -> None:
    program = (
        "from typing import TypedDict\n"
        "from typeforge import Fields, Is, Map, Record, type_function\n"
        "class Left(TypedDict):\n    value: int\n"
        "class Right(TypedDict):\n    value: int\n"
        "class Changed_Left_2:\n    pass\n"
        "@type_function\ndef Changed[T]():\n"
        "    return Record(\n"
        "        field.replace(type=Map[T, Is[Left | Right]: str, ...: field.type])\n"
        "        for field in Fields[T]\n"
        "    )\n"
    )
    source = tmp_path / "identity.py"
    source.write_text(
        program + "type First = Changed[Left | Right]\n"
        "type Repeated = Changed[Left | Right]\n"
        "type Reverse = Changed[Right | Left]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap().content
    assert "type First = Changed_Left_3 | Changed_Right_2" in generated
    assert "type Repeated = Changed_Left_3 | Changed_Right_2" in generated
    assert "type Reverse = Changed_Right_2 | Changed_Left_3" in generated
    assert generated.count("class Changed_Left_3(") == 1
    assert generated.count("class Changed_Right_2(") == 1
    assert generated == generate_module(source, maximum_arity=1).unwrap().content


def test_overlapping_record_layouts_keep_complete_transformed_values(
    tmp_path: Path,
) -> None:
    program = (
        "from typing import TypedDict\n"
        "from typeforge import Fields, Record, type_function\n"
        "class Left(TypedDict):\n    x: int\n    y: str\n"
        "class Right(TypedDict):\n    x: bytes\n    y: float\n"
        "@type_function\ndef Listed[T]():\n"
        "    return Record(\n"
        "        field.replace(type=list[field.type]) for field in Fields[T]\n"
        "    )\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Listed[Left | Right]", namespace)
    adapter = TypeAdapter(Schema[selected])
    for value in (
        {"x": [1], "y": ["text"]},
        {"x": [b"data"], "y": [1.5]},
    ):
        validated = adapter.validate_python(value, strict=True)
        assert validated == value
        assert adapter.dump_python(validated, warnings="error") == value

    for invalid in (
        {"x": [1], "y": [1.5]},
        {"x": [b"data"], "y": ["text"]},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid, strict=True)

    source = tmp_path / "overlap.py"
    source.write_text(program + "type Result = Listed[Left | Right]\n")
    generated = generate_module(source, maximum_arity=1).unwrap().content
    assert "type Result = Listed_Left | Listed_Right" in generated
    left = generated.split("class Listed_Left", 1)[1].split("\n\n", 1)[0]
    right = generated.split("class Listed_Right", 1)[1].split("\n\n", 1)[0]
    assert "x: list[int]" in left and "y: list[str]" in left
    assert "x: list[bytes]" in right and "y: list[float]" in right


def test_constant_union_specialization_avoids_authored_class_names(
    tmp_path: Path,
) -> None:
    program = _PROGRAM + (
        "class Fixed_Left_Left:\n    pass\n"
        "@type_function\ndef Fixed[T]():\n"
        "    return Record(field for field in Fields[Left | Right])\n"
        "type Result = Fixed[Left]\n"
    )
    source = tmp_path / "constant_names.py"
    source.write_text(program)
    generated = generate_module(source, maximum_arity=1).unwrap().content
    assert "type Result = Fixed_Left_Left_2 | Fixed_Left_Right" in generated
    assert generated.count("class Fixed_Left_Left:") == 1
    assert generated.count("class Fixed_Left_Left_2(") == 1


@pytest.mark.parametrize("operand", ["Never", "Left | None", "Left | list[int]"])
def test_unsupported_record_sentinels_do_not_become_empty_records(
    tmp_path: Path, operand: str
) -> None:
    program = _PROGRAM + "from typing import Never\n"
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval(f"Public[{operand}]", namespace)
    with pytest.raises(PydanticSchemaGenerationError, match="unsupported_record"):
        TypeAdapter(Schema[selected])

    source = tmp_path / "sentinel.py"
    source.write_text(program + f"type Result = Public[{operand}]\n")
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, RecordMaterializationError)
    assert error.declaration == "Result"
    assert error.expression == f"Public[{operand}]"


def test_generic_models_rebuild_record_unions_without_replaying_templates() -> None:
    program = _PROGRAM.replace(
        "@type_function\ndef Public[T]():\n",
        "@type_function\ndef Public[T]():\n    constructions.append('Public')\n",
    )
    constructions: list[str] = []
    namespace: dict[str, object] = {
        "__name__": __name__,
        "constructions": constructions,
    }
    exec(
        program
        + (
            "from pydantic import BaseModel\n"
            "from typeforge.pydantic import Schema\n"
            "class Model[T](BaseModel):\n    value: Schema[Public[T]]\n"
        ),
        namespace,
    )
    model: object = eval("Model[Left | Right]", namespace)
    namespace["model"] = model
    value = {"kind": "right", "payload": "text", "right_only": b"data"}
    namespace["value"] = value
    assert eval("model(value=value).value", namespace) == value
    schema: object = eval("model.model_json_schema()", namespace)
    exec("model.model_rebuild(force=True)", namespace)
    assert eval("model.model_json_schema()", namespace) == schema
    assert eval("model(value=value).value", namespace) == value
    assert constructions == ["Public"]
