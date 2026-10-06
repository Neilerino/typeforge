"""Union replacement effects through both production frontends."""

from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from pydantic.errors import PydanticSchemaGenerationError
from returns.result import Failure

from pydantic import TypeAdapter, ValidationError
from typeforge import semantics as s
from typeforge.compiler.pipeline import generate_module
from typeforge.compiler.record_materialization import build_record_shapes
from typeforge.compiler.semantic_adapter import (
    COMPILER_TYPE_SYSTEM,
    NamedType,
    lower_semantic_expression,
)
from typeforge.compiler.source import parse_source
from typeforge.pydantic import Schema

_PROGRAM = (
    "from typing import NotRequired, ReadOnly, TypedDict\n"
    "from typeforge import Drop, Fields, Is, Map, Record, type_function\n"
    "class Row(TypedDict):\n"
    "    count: int\n"
    "    label: NotRequired[ReadOnly[str]]\n"
    "    value: NotRequired[ReadOnly[int | str]]\n"
    "@type_function\ndef WithoutIntegers[T]():\n"
    "    type DropCondition[A] = Map[A, int: Drop, ...: A]\n"
    "    return Record(\n"
    "        field.replace(type=DropCondition[field.type])\n"
    "        for field in Fields[T]\n"
    "    )\n"
)


def test_one_concrete_drop_removes_the_whole_union_field(tmp_path: Path) -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    exec(_PROGRAM, namespace)
    selected: object = eval("WithoutIntegers[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({"label": "text", "value": 1}) == {"label": "text"}
    assert list(adapter.json_schema()["properties"]) == ["label"]
    assert adapter.json_schema()["properties"]["label"]["readOnly"] is True

    source = tmp_path / "field_union.py"
    source.write_text(_PROGRAM + "type Result = WithoutIntegers[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    result = generated.content.split("class WithoutIntegers_Row", 1)[1].split(
        "\n\n", 1
    )[0]
    assert "label: tf_typing.NotRequired[tf_typing.ReadOnly[str]]" in result
    assert "value:" not in result and "count:" not in result


@pytest.mark.parametrize(
    ("prefix", "annotation", "selector", "properties"),
    [
        pytest.param(
            "type Choice = int | str\n",
            "Choice",
            "int",
            ["label"],
        ),
        pytest.param(
            "type Choice[A] = A | str\n",
            "Choice[int]",
            "int",
            ["label"],
        ),
        ("", "str | int", "int", ["label"]),
        ("", "bool | str", "int", ["label"]),
        ("from typing import Any\n", "Any | str", "int", ["label"]),
        ("", "list[int | str]", "int", ["label", "value"]),
        pytest.param(
            "class Animal: pass\nclass Dog(Animal): pass\n",
            "Dog | str",
            "Animal",
            ["count", "label"],
        ),
    ],
)
def test_field_union_type_facts_agree_across_frontends(
    tmp_path: Path,
    prefix: str,
    annotation: str,
    selector: str,
    properties: list[str],
) -> None:
    program = (
        _PROGRAM.replace("class Row(TypedDict):", prefix + "class Row(TypedDict):")
        .replace("ReadOnly[int | str]", f"ReadOnly[{annotation}]")
        .replace("int: Drop", f"{selector}: Drop")
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("WithoutIntegers[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert list(adapter.json_schema()["properties"]) == properties

    source = tmp_path / "field_facts.py"
    source.write_text(program + "type Result = WithoutIntegers[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    result = generated.content.split("class WithoutIntegers_Row", 1)[1].split(
        "\n\n", 1
    )[0]
    assert ("value:" in result) == ("value" in properties)
    assert ("count:" in result) == ("count" in properties)
    assert "label: tf_typing.NotRequired[tf_typing.ReadOnly[str]]" in result


def test_inherited_union_fields_retain_the_same_drop_and_flag_rules(
    tmp_path: Path,
) -> None:
    program = _PROGRAM.replace(
        "class Row(TypedDict):",
        "class Base(TypedDict):\n"
        "    value: NotRequired[ReadOnly[int | str]]\n"
        "class Row(Base):",
    ).replace(
        "    value: NotRequired[ReadOnly[int | str]]\n@type_function", "@type_function"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("WithoutIntegers[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({"label": "text", "value": 1}) == {"label": "text"}
    assert list(adapter.json_schema()["properties"]) == ["label"]

    source = tmp_path / "inherited_union.py"
    source.write_text(program + "type Result = WithoutIntegers[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    result = generated.content.split("class WithoutIntegers_Row", 1)[1].split(
        "\n\n", 1
    )[0]
    assert "value:" not in result and "count:" not in result


def test_exact_is_keeps_the_complete_union_field_and_flags(tmp_path: Path) -> None:
    program = _PROGRAM.replace("int: Drop", "Is[int]: Drop")
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("WithoutIntegers[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({"value": 1}) == {"value": 1}
    assert adapter.validate_python({"value": "text"}) == {"value": "text"}
    assert adapter.validate_python({}) == {}
    assert list(adapter.json_schema()["properties"]) == ["label", "value"]
    assert adapter.json_schema()["properties"]["value"]["readOnly"] is True

    source = tmp_path / "exact_union.py"
    source.write_text(program + "type Result = WithoutIntegers[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    result = generated.content.split("class WithoutIntegers_Row", 1)[1].split(
        "\n\n", 1
    )[0]
    assert "value: tf_typing.NotRequired[tf_typing.ReadOnly[int | str]]" in result
    assert "count:" not in result


def test_drop_does_not_hide_an_uncovered_union_member(tmp_path: Path) -> None:
    program = _PROGRAM.replace(", ...: A", "").replace(
        "    label: NotRequired[ReadOnly[str]]\n", ""
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("WithoutIntegers[Row]", namespace)
    with pytest.raises(PydanticSchemaGenerationError, match="map_no_match"):
        TypeAdapter(Schema[selected])

    source = tmp_path / "uncovered.py"
    source.write_text(program + "type Result = WithoutIntegers[Row]\n")
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    assert "no case matched" in result.failure().message


def test_annotation_metadata_does_not_hide_union_members(tmp_path: Path) -> None:
    program = _PROGRAM.replace(
        "from typing import ", "from typing import Annotated, "
    ).replace("ReadOnly[int | str]", "ReadOnly[Annotated[int | str, 'choice']]")
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("WithoutIntegers[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert list(adapter.json_schema()["properties"]) == ["label"]

    source = tmp_path / "annotated_union.py"
    source.write_text(program + "type Result = WithoutIntegers[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    result = generated.content.split("class WithoutIntegers_Row", 1)[1].split(
        "\n\n", 1
    )[0]
    assert "value:" not in result and "count:" not in result


def test_speculative_capture_drop_does_not_claim_a_definite_field_layout() -> None:
    source = (
        "from typing import TypedDict\n"
        "from typeforge import Capture, Drop, Fields, Map, Record, type_function\n"
        "class Row(TypedDict):\n    value: int\n"
        "@type_function\ndef Transform[U]():\n"
        "    Item = Capture('Item')\n    Other = Capture('Other')\n"
        "    return Record(\n"
        "        field.replace(type=Map[\n"
        "            tuple[int, str, U],\n"
        "            tuple[Item, str, int] | tuple[int, Item, Other]:\n"
        "                Map[Item, int: Drop, ...: Item],\n"
        "        ]) for field in Fields[Row]\n"
        "    )\n"
    )
    module = parse_source(source).unwrap().source
    (record,) = build_record_shapes(module.typed_dicts).unwrap()
    unknown = s.UnresolvedType(NamedType("U"), s.TypeSymbol(("Transform",), "U"))
    expression = lower_semantic_expression(
        module.aliases[0].value, (("Row", record), ("U", unknown))
    )
    result = s.evaluate(expression, COMPILER_TYPE_SYSTEM)
    assert isinstance(result, Failure)
    assert result.failure().code is s.SemanticIssueCode.EXPECTED_TYPE


@pytest.mark.parametrize(
    ("rule", "expected_type"),
    [
        ("Map[A, int: bytes, str: float]", "bytes | float"),
        ("Map[A, int: bytes, ...: list[A]]", "bytes | list[int | str]"),
    ],
)
def test_union_replacements_keep_member_outputs_and_the_original_parameter(
    tmp_path: Path, rule: str, expected_type: str
) -> None:
    program = _PROGRAM.replace("Map[A, int: Drop, ...: A]", rule)
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("WithoutIntegers[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({"count": b"one", "value": b"two"}) == {
        "count": b"one",
        "value": b"two",
    }
    sample: object = 1.5 if rule.endswith("str: float]") else [1, "text"]
    assert (
        adapter.validate_python({"count": b"one", "value": sample})["value"] == sample
    )
    assert adapter.json_schema()["properties"]["value"]["readOnly"] is True

    source = tmp_path / "replace_union.py"
    source.write_text(program + "type Result = WithoutIntegers[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap().content
    assert (
        f"value: tf_typing.NotRequired[tf_typing.ReadOnly[{expected_type}]]"
        in generated
    )


@pytest.mark.parametrize("drop", [False, True])
def test_capture_alternatives_keep_complete_outputs_inside_replacements(
    tmp_path: Path, drop: bool
) -> None:
    output = "Map[Item, int: Drop, ...: Item]" if drop else "tuple[Item, Item]"
    program = _PROGRAM.replace(
        "from typeforge import ", "from typeforge import Capture, "
    ).replace("ReadOnly[int | str]", "ReadOnly[tuple[int, str]]")
    program = program.replace(
        "    type DropCondition[A] = Map[A, int: Drop, ...: A]",
        "    Item = Capture('Item')\n"
        "    type DropCondition[A] = Map[A, "
        f"tuple[Item, str] | tuple[int, Item]: {output}, ...: A]",
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("WithoutIntegers[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    if drop:
        assert "value" not in adapter.json_schema()["properties"]
    else:
        for value in ((1, 2), ("one", "two")):
            assert (
                adapter.validate_python({"count": 1, "value": value}, strict=True)[
                    "value"
                ]
                == value
            )

        with pytest.raises(ValidationError):
            adapter.validate_python({"count": 1, "value": (1, "mixed")}, strict=True)

    source = tmp_path / "capture_replacement.py"
    source.write_text(program + "type Result = WithoutIntegers[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap().content
    result = generated.split("class WithoutIntegers_Row", 1)[1].split("\n\n", 1)[0]
    if drop:
        assert "value:" not in result
    else:
        assert "tuple[int, int] | tuple[str, str]" in result


@pytest.mark.parametrize(
    "expression",
    [
        "field.replace(name=Drop)",
        "field.replace(type=list[Map[field.type, int: Drop, ...: str]])",
        "Field(name=field.name, type=Map[field.type, int: Drop, ...: str])",
    ],
)
def test_drop_is_consumed_only_at_the_replacement_type_position(
    tmp_path: Path, expression: str
) -> None:
    program = _PROGRAM.replace(
        "from typeforge import ", "from typeforge import Field, "
    ).replace("field.replace(type=DropCondition[field.type])", expression)
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("WithoutIntegers[Row]", namespace)
    with pytest.raises(PydanticSchemaGenerationError):
        TypeAdapter(Schema[selected])

    source = tmp_path / "invalid_drop.py"
    source.write_text(program + "type Result = WithoutIntegers[Row]\n")
    assert isinstance(generate_module(source, maximum_arity=1), Failure)


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_checkers_observe_dropped_fields_union_values_and_readonly_flags(
    tmp_path: Path, checker: str
) -> None:
    encoded = (
        _PROGRAM.split("@type_function", 1)[1]
        .replace("WithoutIntegers", "Encoded")
        .replace("Map[A, int: Drop, ...: A]", "Map[A, int: bytes, str: float]")
    )
    library = tmp_path / "library.py"
    library.write_text(
        _PROGRAM
        + "@type_function"
        + encoded
        + "type Dropped = WithoutIntegers[Row]\ntype Changed = Encoded[Row]\n"
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
    accepted_source = (
        "from typing import assert_type\nfrom library import Dropped, Changed\n"
        "empty: Dropped = {}\nfirst: Changed = {'count': b'one', 'value': b'two'}\n"
        "second: Changed = {'count': b'one', 'value': 1.5}\n"
        "def check(value: Changed) -> None:\n"
        "    if 'value' in value:\n        assert_type(value['value'], bytes | float)\n"
    )
    consumer.write_text(accepted_source)
    accepted = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    consumer.write_text(
        accepted_source + "    value['value'] = b'edited'\nempty['value'] = 1\n"
    )
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "value" in rejected.stdout + rejected.stderr


def test_passthrough_does_not_require_recursive_alias_selection(tmp_path: Path) -> None:
    program = (
        "from typing import TypedDict\n"
        "from typeforge import Fields, Record, type_function\n"
        "type Tree = int | list[Tree]\n"
        "class Row(TypedDict):\n    value: Tree\n"
        "@type_function\ndef Copy[T]():\n"
        "    return Record(field for field in Fields[T])\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    selected: object = eval("Copy[Row]", namespace)
    adapter = TypeAdapter(Schema[selected])
    assert adapter.validate_python({"value": [1, [2]]}) == {"value": [1, [2]]}

    source = tmp_path / "passthrough_alias.py"
    source.write_text(program + "type Result = Copy[Row]\n")
    generated = generate_module(source, maximum_arity=1).unwrap().content
    assert "value: Tree" in generated
