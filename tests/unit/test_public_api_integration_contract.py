"""Reusable public interfaces across publication, editors, and runtime models."""

import sys
from pathlib import Path
from subprocess import run
from sys import executable
from types import ModuleType

import pytest
from returns.result import Failure

from pydantic import TypeAdapter, ValidationError
from typeforge.adapters.pyrefly import PyreflyAdapter
from typeforge.analysis.model import AnalysisRequest, HoverQuery, SourcePosition
from typeforge.compiler.pipeline import compile_source, generate_module
from typeforge.compiler.record_materialization import RecordMaterializationError
from typeforge.compiler.stub_ir import VariableDeclaration
from typeforge.overlay import transform_source
from typeforge.pydantic import Schema

_LIBRARY = """from typing import Literal, TypedDict
from typeforge import Drop, Fields, Map, Record, type_function

class Left(TypedDict):
    kind: Literal['left']
    payload: int
    secret: str

class Right(TypedDict):
    kind: Literal['right']
    payload: str
    secret: bytes

@type_function
def Public[T]():
    return Record(
        Map[field.name, Literal['secret']: Drop, ...: field]
        for field in Fields[T]
    )

@type_function
def Items[T]():
    return list[T]

@type_function
def Selected[T]():
    type Local[A] = Map[A, int: str, ...: bytes]
    return Local[T]

type Result = Public[Left | Right]
type Names = Items[str]
VERSION: int = 1 // 0
DEFAULT: Public[Left | Right]
TEXT: Selected[int]
INLINE: list[Map[int, int: str, ...: bytes]]

def encode[T](value: T) -> Map[T, int: str, ...: bytes]: ...
"""


def _publish(directory: Path) -> str:
    library = directory / "library.py"
    library.write_text(_LIBRARY)
    content = generate_module(library, maximum_arity=2).unwrap().content
    library.with_suffix(".pyi").write_text(content)
    return content


def test_public_variables_keep_concrete_transforms_and_complete_record_unions(
    tmp_path: Path,
) -> None:
    content = _publish(tmp_path)
    assert "DEFAULT: Public_Left | Public_Right" in content
    assert "TEXT: str" in content
    assert "VERSION: int" in content
    assert "INLINE: list[str | bytes]" in content
    assert content.count("DEFAULT:") == 1
    assert content.count("TEXT:") == 1
    assert content == _publish(tmp_path)


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_published_barrel_composes_native_aliases_and_checks_complete_outputs(
    tmp_path: Path, checker: str
) -> None:
    published = _publish(tmp_path)
    facade = tmp_path / "facade.py"
    facade.write_text(
        "from library import DEFAULT, TEXT, VERSION, Items, Result, Selected, encode\n"
        "from typeforge import type_function\n"
        "__all__ = ['DEFAULT', 'TEXT', 'VERSION', 'Items', 'Result', "
        "'Selected', 'encode']\n"
        "type Names = Items[str]\n"
        "@type_function\ndef Forwarded[T]():\n    return Items[T]\n"
    )
    facade.with_suffix(".pyi").write_text(
        generate_module(facade, maximum_arity=2).unwrap().content
    )
    (tmp_path / "library.py").unlink()
    facade.unlink()
    (tmp_path / "pyrightconfig.json").write_text(
        '{"pythonVersion": "3.14", "typeCheckingMode": "strict"}'
    )
    (tmp_path / "pyrefly.toml").write_text('python-version = "3.14"\n')
    commands = {
        "mypy": (executable, "-m", "mypy", "--strict", "--config-file", "/dev/null"),
        "pyright": (executable, "-m", "pyright", "--pythonpath", executable),
        "pyrefly": (str(Path(executable).with_name("pyrefly")), "check"),
    }
    consumer = tmp_path / "consumer.py"
    program = (
        "from typing import assert_type\n"
        "from facade import DEFAULT, TEXT, VERSION, Forwarded, Names, "
        "Result, Selected, encode\n"
        "assert_type(TEXT, str)\nassert_type(VERSION, int)\n"
        "assert_type(encode(1), str)\nassert_type(encode('text'), str | bytes)\n"
        "names: Names = ['name']\n"
        "def composed(value: Forwarded[int], encoded: Selected[int]) -> None:\n"
        "    assert_type(value, list[int])\n"
        "    assert_type(encoded, str | bytes)\n"
        "left: Result = {'kind': 'left', 'payload': 1}\n"
        "right: Result = {'kind': 'right', 'payload': 'text'}\n"
        "def inspect(value: Result) -> None:\n"
        "    if value['kind'] == 'left':\n"
        "        assert_type(value['payload'], int)\n"
        "    else:\n        assert_type(value['payload'], str)\n"
        "inspect(DEFAULT)\n"
    )
    consumer.write_text(program)
    accepted = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert accepted.returncode == 0, published + accepted.stdout + accepted.stderr
    consumer.write_text(
        program + "wrong: Result = {'kind': 'left', 'payload': 'crossed'}\n"
    )
    rejected = run(
        (*commands[checker], str(consumer)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "Public_Left" in rejected.stdout + rejected.stderr


def test_cross_module_runtime_templates_rebuild_independent_specializations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = ModuleType("typeforge_integration_library")
    monkeypatch.setitem(sys.modules, library.__name__, library)
    constructions: list[str] = []
    library.__dict__["constructions"] = constructions
    runtime_source = _LIBRARY.replace("VERSION: int = 1 // 0", "VERSION: int = 1")
    for name in ("Public", "Items", "Selected"):
        runtime_source = runtime_source.replace(
            f"def {name}[T]():\n",
            f"def {name}[T]():\n    constructions.append('{name}')\n",
        )

    exec(runtime_source, library.__dict__)
    models = ModuleType("typeforge_integration_models")
    monkeypatch.setitem(sys.modules, models.__name__, models)
    models.__dict__["constructions"] = constructions
    exec(
        "from typing import TypedDict\n"
        "from pydantic import BaseModel\n"
        "from typeforge import Drop, Fields, Map, Record, type_function\n"
        "from typeforge.pydantic import Schema\n"
        "from typeforge_integration_library import Left, Right, Public, Selected\n"
        "@type_function\ndef Visible[T]():\n"
        "    constructions.append('Visible')\n    return Public[T]\n"
        "@type_function\ndef WithoutIntegers[T]():\n"
        "    constructions.append('WithoutIntegers')\n"
        "    type DropCondition[A] = Map[A, int: Drop, ...: A]\n"
        "    return Record(\n"
        "        field.replace(type=DropCondition[field.type])\n"
        "        for field in Fields[Public[T]]\n    )\n"
        "class Mixed(TypedDict):\n    value: int | str\n    secret: str\n"
        "class Model[T](BaseModel):\n    value: Schema[Visible[T]]\n"
        "class Scalar[T](BaseModel):\n    value: Schema[Selected[T]]\n"
        "left = Model[Left]\nright = Model[Right]\nboth = Model[Left | Right]\n"
        "text = Scalar[int]\nbinary = Scalar[str]\n",
        models.__dict__,
    )
    left = {"kind": "left", "payload": 1}
    right = {"kind": "right", "payload": "text"}
    cases = (
        ("left", left, right),
        ("right", right, left),
        ("both", left, {"kind": "left", "payload": "crossed"}),
        ("text", "text", b"binary"),
        ("binary", b"binary", "text"),
    )
    schemas: dict[str, object] = {}
    for _ in range(2):
        for name, valid, invalid in cases:
            model = models.__dict__[name]
            models.__dict__["current"] = model
            models.__dict__["valid"] = valid
            models.__dict__["invalid"] = invalid
            assert eval("current(value=valid).value", models.__dict__) == valid
            with pytest.raises(ValidationError):
                eval(
                    "current.model_validate({'value': invalid}, strict=True)",
                    models.__dict__,
                )

            schema: object = eval("current.model_json_schema()", models.__dict__)
            if name in schemas:
                assert schema == schemas[name]

            schemas[name] = schema
            assert eval("current.model_rebuild(force=True)", models.__dict__) is True

    selected: object = eval("WithoutIntegers[Mixed]", models.__dict__)
    assert TypeAdapter(Schema[selected]).validate_python({"value": "text"}) == {}
    assert constructions == [
        "Public",
        "Items",
        "Selected",
        "Visible",
        "WithoutIntegers",
    ]


def test_projected_module_variables_preserve_origins_and_cross_module_hover(
    tmp_path: Path,
) -> None:
    _publish(tmp_path)
    source = (
        "from library import Items\n"
        "from typeforge import Map, type_function\n"
        "@type_function\ndef Selected[T]():\n"
        "    return Map[T, int: str, ...: bytes]\n"
        "names: Items[str] = ['name']\n"
        "text: Selected[int] = 'text'\n"
        "wrong: Selected[int] = b'wrong'\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(source)
    (tmp_path / "pyrefly.toml").write_text('python-version = "3.14"\n')
    plan = compile_source(source, path, maximum_arity=2).unwrap()
    variables = {
        item.name: item
        for item in plan.module.declarations
        if isinstance(item, VariableDeclaration)
    }
    for name in ("text", "wrong"):
        assert any(
            origin.generated is variables[name]
            and origin.origin.path == path
            and origin.origin.start.line
            == source[: source.index(name + ":")].count("\n") + 1
            for origin in plan.module.origins
        )

    document = transform_source(source, path, maximum_arity=2).unwrap()
    assert "text: str = 'text'" in document.generated_text
    offset = source.index("text:")
    query = SourcePosition(offset, source[:offset].count("\n"), 0)
    result = (
        PyreflyAdapter(command=(str(Path(executable).with_name("pyrefly")), "lsp"))
        .analyze(
            AnalysisRequest(
                document=document,
                project_root=tmp_path,
                hover_queries=(HoverQuery(query),),
            )
        )
        .unwrap()
    )
    assert len(result.hovers) == 1
    assert "str" in result.hovers[0].contents
    wrong_offset = source.index("b'wrong'")
    assert any(
        item.path == path
        and item.span.start.offset <= wrong_offset < item.span.end.offset
        for item in result.diagnostics
    )


@pytest.mark.parametrize("operand", ["Left | int", "int | Left"])
def test_public_variable_failure_keeps_its_owning_declaration(
    tmp_path: Path,
    operand: str,
) -> None:
    library = tmp_path / "library.py"
    library.write_text(
        _LIBRARY.replace("DEFAULT: Public[Left | Right]", f"DEFAULT: Public[{operand}]")
    )
    result = generate_module(library, maximum_arity=2)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, RecordMaterializationError)
    assert error.declaration == "DEFAULT"
    assert error.expression == f"Public[{operand}]"
    assert "int" in error.message
