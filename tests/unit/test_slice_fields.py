"""Field-transform contracts shared by publication and runtime Schema."""

import json
from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from returns.result import Failure

from pydantic import PydanticSchemaGenerationError, TypeAdapter, ValidationError
from typeforge import semantics as s
from typeforge.compiler.pipeline import generate_module
from typeforge.compiler.record_materialization import (
    RecordMaterializationError,
    build_record_shapes,
)
from typeforge.compiler.semantic_adapter import (
    COMPILER_TYPE_SYSTEM,
    NamedType,
    lower_semantic_expression,
)
from typeforge.compiler.source import parse_source
from typeforge.pydantic import Schema

RECORDS = """\
from typing import Literal, NotRequired, ReadOnly, TypedDict
from typeforge import (
    Case, Default, Drop, Equal, Field, Key, Map, MapFields,
    OptionalField, ReadonlyField, Value,
)
from typeforge.pydantic import Input

class Base(TypedDict, total=False):
    note: ReadOnly[str]

class Row(Base):
    name: str
    password: str
    count: int
    token: ReadOnly[NotRequired[bytes]]
    kind: Literal["a"] | Literal["b"]

type IsName = Equal[Literal["name"]]
"""

SLICED = """Map[Key,
    Literal["password"]: Drop,
    IsName: OptionalField[Literal["display_name"], Value],
    Literal["count"]: ReadonlyField[Key, Map[Value, int: str | None, ...: Value]],
    ...: Field[Key, Value],
]"""

CANONICAL = """Map[Key,
    Case[Literal["password"], Drop],
    Case[IsName, OptionalField[Literal["display_name"], Value]],
    Case[Literal["count"], ReadonlyField[Key,
        Map[Value, Case[int, str | None], Default[Value]]]],
    Default[Field[Key, Value]],
]"""


def _source(transform: str) -> str:
    return (
        RECORDS + f"type Public[T] = MapFields[T, {transform}]\n"
        "def publicize[T](value: T) -> Public[T]: ...\n"
    )


def _runtime_adapter(source: str) -> TypeAdapter[object]:
    # Only fixed test fixtures execute here, separately from compiler generation.
    namespace: dict[str, object] = {"__name__": __name__}
    exec(source, namespace)
    annotation: object = eval("Public[Row]", namespace)
    return TypeAdapter[object](Schema[annotation])


def test_slice_fields_preserve_names_values_modifiers_and_union_outputs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fields.py"
    published: list[str] = []
    schemas: list[dict[str, object]] = []
    for transform in (SLICED, CANONICAL):
        source = _source(transform)
        path.write_text(source)
        published.append(generate_module(path, maximum_arity=2).unwrap().content)
        adapter = _runtime_adapter(source)
        schema = adapter.json_schema()
        schemas.append(schema)

        # Field deliberately makes inherited/readonly optional inputs writable
        # and required; explicit modifiers determine each transformed field.
        assert schema["required"] == ["note", "count", "token", "kind"]
        properties = schema["properties"]
        assert list(properties) == ["note", "display_name", "count", "token", "kind"]
        assert "readOnly" not in properties["note"]
        assert "readOnly" not in properties["token"]
        assert properties["count"]["readOnly"] is True
        assert properties["count"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
        raw = {"note": "ok", "count": None, "token": "abc", "kind": "a"}
        expected = {**raw, "token": b"abc"}
        assert adapter.validate_python(raw) == expected
        assert adapter.validate_python({**raw, "password": "secret"}) == expected
        assert adapter.validate_json(adapter.dump_json(expected)) == expected
        assert adapter.validate_python({**raw, "display_name": "Ada"}) == {
            **expected,
            "display_name": "Ada",
        }
        with pytest.raises(ValidationError) as missing:
            adapter.validate_python({"count": "one", "token": "abc", "kind": "a"})

        assert missing.value.errors()[0]["loc"] == ("note",)
        with pytest.raises(ValidationError):
            adapter.validate_python({**raw, "kind": "wrong"})

    assert published[0] == published[1]
    assert schemas[0] == schemas[1]
    record = published[0].split("class Public_Row", 1)[1].split("\n\n", 1)[0]
    assert (
        record
        == """(tf_typing.TypedDict):
    note: str
    display_name: tf_typing.NotRequired[str]
    count: tf_typing.ReadOnly[str | None]
    token: bytes
    kind: Literal["a"] | Literal["b"]"""
    )


@pytest.mark.parametrize(
    ("transform", "runtime_code", "compiler_message"),
    [
        (
            'Map[Key, ...: Field[Literal["same"], Value]]',
            "duplicate_field",
            "same",
        ),
        ("Map[Key, ...: str]", "expected_field", "field or Drop"),
        (
            "Map[Input, int: Field[Key, Value], ...: Drop]",
            "expected_field",
            "deferred Map outputs must evaluate to types",
        ),
    ],
)
def test_invalid_slice_field_transforms_fail_at_both_boundaries(
    tmp_path: Path, transform: str, runtime_code: str, compiler_message: str
) -> None:
    source = _source(transform)
    path = tmp_path / "invalid.py"
    path.write_text(source)

    result = generate_module(path, maximum_arity=2)
    assert isinstance(result, Failure)
    issue = result.failure()
    assert isinstance(issue, RecordMaterializationError)
    assert issue.declaration == "Public"
    assert compiler_message in issue.message
    with pytest.raises(PydanticSchemaGenerationError, match=runtime_code):
        _runtime_adapter(source)


@pytest.mark.parametrize("record", ["Row | Base", "dict[str, int]", "Plain"])
def test_slice_transforms_do_not_broaden_supported_record_families(
    tmp_path: Path, record: str
) -> None:
    source = _source("Map[Key, ...: Field[Key, Value]]").replace(
        "type Public[T] = MapFields[T,",
        f"class Plain:\n    value: int\n\ntype Public[T] = MapFields[{record},",
    )
    path = tmp_path / "unsupported.py"
    path.write_text(source)

    result = generate_module(path, maximum_arity=2)
    assert isinstance(result, Failure)
    issue = result.failure()
    assert isinstance(issue, RecordMaterializationError)
    assert "supported compiler record" in issue.message
    with pytest.raises(PydanticSchemaGenerationError, match="unsupported_record"):
        _runtime_adapter(source)


def test_slice_field_copy_preserves_each_consumers_metadata_policy(
    tmp_path: Path,
) -> None:
    source = """\
from typing import Annotated, TypedDict
from pydantic import Field as PydanticField
from typeforge import Field, Key, Map, MapFields, Value

class Row(TypedDict):
    count: Annotated[int, PydanticField(gt=0)]

type Public[T] = MapFields[T, Map[Key, ...: Field[Key, Value]]]
def publicize[T](value: T) -> Public[T]: ...
"""
    path = tmp_path / "metadata.py"
    path.write_text(source)

    published = generate_module(path, maximum_arity=2).unwrap().content
    path.write_text(
        source.replace(
            "from typeforge import Field,", "from typeforge import Default, Field,"
        ).replace(
            "Map[Key, ...: Field[Key, Value]]", "Map[Key, Default[Field[Key, Value]]]"
        )
    )
    assert generate_module(path, maximum_arity=2).unwrap().content == published
    record = published.split("class Public_Row", 1)[1].split("\n\n", 1)[0]
    # The source parser strips Annotated metadata for compiler typing. Runtime
    # reflection retains it for Pydantic validation and JSON Schema generation.
    assert record == "(tf_typing.TypedDict):\n    count: int"
    adapter = _runtime_adapter(source)
    assert adapter.validate_python({"count": "3"}) == {"count": 3}
    assert adapter.json_schema()["properties"]["count"]["exclusiveMinimum"] == 0
    with pytest.raises(ValidationError) as failure:
        adapter.validate_python({"count": 0})

    assert failure.value.errors()[0]["loc"] == ("count",)


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_checkers_observe_slice_field_modifiers_and_union_types(
    tmp_path: Path, checker: str
) -> None:
    library = tmp_path / "fields.py"
    # Check the generated record types directly. Generic callable overload
    # ordering across base/derived records is a separate existing limitation.
    source = _source(SLICED).replace(
        "def publicize[T](value: T) -> Public[T]: ...\n", ""
    )
    library.write_text(source)
    published = generate_module(library, maximum_arity=2).unwrap().content
    library.with_suffix(".pyi").write_text(published)
    consumer = tmp_path / "consumer.py"
    consumer.write_text("""\
from typing import Literal, assert_type
from fields import Public_Row

record: Public_Row = {"note": "ok", "count": None, "token": b"x", "kind": "a"}
record["note"] = "changed"
record["token"] = b"changed"

def inspect(value: Public_Row) -> None:
    assert_type(value["count"], str | None)
    assert_type(value["kind"], Literal["a"] | Literal["b"])
""")
    command = [str(Path(executable).with_name(checker))]
    if checker == "mypy":
        command.extend(["--strict", "--no-incremental"])
    elif checker == "pyright":
        (tmp_path / "pyrightconfig.json").write_text(
            json.dumps({"pythonVersion": "3.14", "typeCheckingMode": "standard"})
        )
    else:
        (tmp_path / "pyrefly.toml").write_text('python-version = "3.14"\n')
        command.extend(["check", "--config", "pyrefly.toml"])

    command.append(consumer.name)
    result = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, published + result.stdout + result.stderr

    consumer.write_text(consumer.read_text() + '\nrecord["count"] = "forbidden"\n')
    result = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "count" in result.stdout + result.stderr


@pytest.mark.parametrize("sliced", [False, True])
def test_indeterminate_field_layouts_are_not_treated_as_definite_records(
    sliced: bool,
) -> None:
    transform = (
        "Map[Key, Equal[U, int]: Field[Key, Value], ...: Drop]"
        if sliced
        else "Map[Key, Case[Equal[U, int], Field[Key, Value]], Default[Drop]]"
    )
    source = (
        "from typing import TypedDict\n"
        "from typeforge import Case, Default, Drop, Equal, Field, Key, "
        "Map, MapFields, Value\n"
        "class Row(TypedDict):\n    value: int\n"
        f"type Public[U] = MapFields[Row, {transform}]\n"
    )
    module = parse_source(source).unwrap().source
    (record,) = build_record_shapes(module.typed_dicts)
    unknown = s.UnresolvedType(NamedType("U"), s.TypeSymbol(("Public",), "U"))
    expression = lower_semantic_expression(
        module.aliases[0].value, (("Row", record), ("U", unknown))
    )

    result = s.evaluate(expression, COMPILER_TYPE_SYSTEM)
    assert isinstance(result, Failure)
    assert result.failure().code is s.SemanticIssueCode.EXPECTED_TYPE
