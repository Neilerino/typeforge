"""Compiler integration regressions carried forward from the slice-syntax POC."""

import json
from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from returns.result import Failure

from typeforge.compiler.pipeline import compile_source, generate_module
from typeforge.compiler.source import MarkerKind, MarkerTypeExpression, parse_source
from typeforge.overlay import transform_source

IMPORTS = """\
from typing import Literal, Never, TypedDict, Annotated
from typeforge import Map, Case, Default, Equal, Assignable, All, Not
from typeforge import MapFields, Field, OptionalField, Drop, Key, Value
from typeforge.pydantic import Schema
"""


@pytest.mark.parametrize(
    ("sliced", "canonical"),
    [
        (
            "Map[T, int: str, bytes: int, ...: T]",
            "Map[T, Case[int, str], Case[bytes, int], Default[T]]",
        ),
        (
            "Map[T, Assignable[int]: str, ...: bytes]",
            "Map[T, Case[Assignable[T, int], str], Default[bytes]]",
        ),
        (
            "Map[T, All[Assignable[int], Not[Equal[bool]]]: str, ...: bytes]",
            "Map[T, Case[All[Assignable[T, int], Not[Equal[T, bool]]], str], "
            "Default[bytes]]",
        ),
        (
            "Map[T, True: str, ...: bytes]",
            "Map[T, Case[Literal[True], str], Default[bytes]]",
        ),
        (
            'Map[T, Literal["text"]: str, ...: bytes]',
            'Map[T, Case[Literal["text"], str], Default[bytes]]',
        ),
        (
            "Map[T, -1: str, ...: bytes]",
            "Map[T, Case[Literal[-1], str], Default[bytes]]",
        ),
        ("Map[T, int: str]", "Map[T, Case[int, str]]"),
        ("Map[T, int: Never]", "Map[T, Case[int, Never]]"),
    ],
)
def test_slice_callables_emit_the_same_stubs_as_existing_syntax(
    tmp_path: Path, sliced: str, canonical: str
) -> None:
    path = tmp_path / "example.py"
    outputs: list[str] = []
    for expression in (sliced, canonical):
        path.write_text(IMPORTS + f"def convert[T](value: T) -> {expression}: ...\n")
        outputs.append(generate_module(path, maximum_arity=2).unwrap().content)

    assert outputs[0] == outputs[1]


@pytest.mark.parametrize(
    ("sliced", "canonical"),
    [
        ("Map[int, int: str, ...: bytes]", "Map[int, Case[int, str], Default[bytes]]"),
        (
            "Map[bool, Assignable[int]: str, ...: bytes]",
            "Map[bool, Case[Assignable[bool, int], str], Default[bytes]]",
        ),
        (
            'Map[Literal["text"], Literal["text"]: str, ...: bytes]',
            'Map[Literal["text"], Case[Literal["text"], str], Default[bytes]]',
        ),
        (
            "Map[list[int], list[Value]: Map[Value, Equal[int]: str, ...: bytes]]",
            "Map[list[int], Case[list[Value], Map[Value, "
            "Case[Equal[Value, int], str], Default[bytes]]]]",
        ),
        (
            "Map[int, int: Map[str, Assignable[str]: bytes, ...: float]]",
            "Map[int, Case[int, Map[str, "
            "Case[Assignable[str, str], bytes], Default[float]]]]",
        ),
    ],
)
def test_schema_boundaries_emit_the_same_types(
    tmp_path: Path, sliced: str, canonical: str
) -> None:
    path = tmp_path / "example.py"
    outputs: list[str] = []
    for expression in (sliced, canonical):
        path.write_text(
            IMPORTS + f"def accept(value: Schema[{expression}]) -> None: ...\n"
        )
        outputs.append(generate_module(path, maximum_arity=2).unwrap().content)

    assert outputs[0] == outputs[1]


def test_source_normalization_retains_authored_branch_spans() -> None:
    text = (
        "from typeforge import Map\ndef f[T](x: T) -> Map[T, int: str, ...: T]: ...\n"
    )
    module = parse_source(text).unwrap().source
    expression = module.functions[0].returns
    assert isinstance(expression, MarkerTypeExpression)
    case, default = expression.arguments[1:]
    assert isinstance(case, MarkerTypeExpression)
    assert isinstance(default, MarkerTypeExpression)
    assert case.marker is MarkerKind.CASE
    assert case.source == "int: str"
    assert case.span.start.column == text.splitlines()[1].index("int: str")
    assert default.marker is MarkerKind.DEFAULT
    assert default.source == "...: T"


def test_record_alias_slices_use_existing_materialization(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    source = (
        IMPORTS
        + """\
class User(TypedDict):
    name: str
    password: str
    age: int

type Public[T] = MapFields[T, Map[Key,
    Literal["password"]: Drop,
    Literal["name"]: OptionalField[Literal["display_name"], Value],
    ...: Field[Key, Value],
]]

def publicize[T](value: T) -> Public[T]: ...
"""
    )
    path.write_text(source)
    content = generate_module(path, maximum_arity=2).unwrap().content
    result = content.split("class Public_User", 1)[1].split("\n\n", 1)[0]
    assert "password" not in result
    assert "display_name: tf_typing.NotRequired[str]" in result
    assert "age: int" in result


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
@pytest.mark.parametrize("projection", ["alias", "inline", "stub"])
def test_real_checkers_accept_aliases_but_inline_slices_need_projection_changes(
    tmp_path: Path, checker: str, projection: str
) -> None:
    source = """\
from typing import assert_type
from typeforge import Map

type Encoded[T] = Map[T, int: str, ...: T]

def encode[T](value: T) -> Encoded[T]:
    if type(value) is int:
        return str(value)
    return value

assert_type(encode(1), str)
"""
    if projection in {"inline", "stub"}:
        source = source.replace("type Encoded[T] = Map[T, int: str, ...: T]\n", "")
        source = source.replace("-> Encoded[T]", "-> Map[T, int: str, ...: T]")

    path = tmp_path / "example.py"
    overlay = transform_source(source, path, maximum_arity=2).unwrap()
    assert overlay.authored_text == source
    path.write_text(overlay.generated_text)
    if projection == "stub":
        path.write_text(source.replace("assert_type(encode(1), str)", ""))
        path.with_suffix(".pyi").write_text(
            generate_module(path, maximum_arity=2).unwrap().content
        )
        path = tmp_path / "consumer.py"
        path.write_text(
            "from typing import assert_type\nfrom example import encode\n"
            "assert_type(encode(1), str)\n"
        )

    command = [str(Path(executable).with_name(checker))]
    if checker == "mypy":
        command.extend(["--strict", "--no-incremental", "--follow-imports=silent"])
    elif checker == "pyright":
        config = tmp_path / "pyrightconfig.json"
        config.write_text(
            json.dumps(
                {
                    "pythonVersion": "3.14",
                    "typeCheckingMode": "standard",
                    "extraPaths": [str(Path("src").resolve())],
                }
            )
        )
        command.extend(["--project", str(config)])
    elif checker == "pyrefly":
        command.extend(
            [
                "check",
                "--config",
                str(Path("pyproject.toml").resolve()),
                "--python-interpreter-path",
                executable,
                "--search-path",
                str(tmp_path),
                "--search-path",
                str(Path("src").resolve()),
            ]
        )

    result = run([*command, str(path)], capture_output=True, text=True, check=False)
    if projection == "inline":
        # Existing overlays leave the implementation annotation untouched.
        # Characterize the blocker instead of changing projection in this POC.
        assert result.returncode != 0
        assert "slice" in result.stdout + result.stderr or (
            "Invalid type comment or annotation" in result.stdout
        )
        return

    assert result.returncode == 0, result.stdout + result.stderr

    if projection == "stub":
        path.write_text(path.read_text().replace("encode(1), str", "encode(1), int"))
    else:
        broken = source.replace("return str(value)", "return 123")
        path.write_text(
            transform_source(broken, path, maximum_arity=2).unwrap().generated_text
        )

    result = run([*command, str(path)], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "str" in result.stdout + result.stderr


def test_unbounded_structural_callable_has_the_same_existing_emission_limit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "example.py"
    for expression in (
        "Map[T, list[Value]: tuple[Value, ...], ...: bytes]",
        "Map[T, Case[list[Value], tuple[Value, ...]], Default[bytes]]",
    ):
        path.write_text(IMPORTS + f"def f[T](x: T) -> {expression}: ...\n")
        result = generate_module(path, maximum_arity=2)
        assert isinstance(result, Failure)
        assert "unlowered type expression: MapValueType" in str(result.failure())


def test_unary_predicate_alias_requires_normalization_after_alias_expansion() -> None:
    source = """\
from typeforge import Map, Assignable
type Numeric = Assignable[int]
def f[T](x: T) -> Map[T, Numeric: str, ...: bytes]: ...
"""
    result = compile_source(source, Path("example.py"), maximum_arity=2)
    assert isinstance(result, Failure)
    assert "Assignable requires two type arguments" in str(result.failure())


def test_compilation_never_imports_or_executes_authored_code(tmp_path: Path) -> None:
    path = tmp_path / "not_executed.py"
    path.write_text(
        "from typeforge import Map\n"
        "_tripwire: int = 1 // 0\n"
        "def f[T](x: T) -> Map[T, int: str, ...: T]: ...\n"
    )
    result = generate_module(path, maximum_arity=2).unwrap()
    assert "def f(x: int) -> str" in result.content


def test_module_qualified_map_and_predicates_resolve_at_the_parser() -> None:
    source = """\
import typeforge as tf
def f[T](x: T) -> tf.Map[T, tf.Assignable[int]: str, ...: T]: ...
"""
    plan = compile_source(source, Path("example.py"), maximum_arity=2).unwrap()
    assert plan.module.declarations
