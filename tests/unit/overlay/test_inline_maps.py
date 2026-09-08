import ast
import json
from pathlib import Path
from subprocess import run
from sys import executable
from unittest.mock import patch

import pytest

from typeforge.analysis import MappingKind
from typeforge.analysis.mapping import generated_to_authored
from typeforge.compiler.pipeline import compile_source
from typeforge.compiler.stub_ir import TypeName
from typeforge.overlay import project_overlay, transform_source


def test_inline_return_projects_fallback_and_retains_return_verification() -> None:
    source = """\
from typeforge import Map
def encode[T](value: T) -> Map[T, int: str, ...: T]:
    if type(value) is int:
        return value
    return value
"""
    document = transform_source(source, Path("inline.py")).unwrap()

    assert "\ndef encode[T](value: T) -> str | T:\n" in document.generated_text
    assert "def encode(value: int) -> str: ..." in document.generated_text
    assert "__typeforge_return_1: str = value" in document.generated_text
    assert document.authored_text == source
    checks = [mapping.provenance for mapping in document.mappings if mapping.provenance]
    assert checks[0].return_annotation == "Map[T, int: str, ...: T]"


def test_nested_annotations_methods_and_schema_edits_do_not_overlap() -> None:
    source = """\
from typeforge import Map, Equal
from typeforge.pydantic import Schema
class Example[T]:
    field: tuple[Map[T, int: str, ...: bytes], Map[T, str: int]]
    def convert(self, value: list[Map[T, int: str, ...: bytes]]) -> list[Map[
        T, int: tuple[Map[bytes, bytes: str]], ...: bytes
    ]]:
        raise RuntimeError
    def checked(self, value: T) -> Map[T, Equal[T, Schema[int]]: str, ...: bytes]:
        raise RuntimeError
"""
    plan = compile_source(source, Path("nested.py"), maximum_arity=2).unwrap()
    with patch("ast.parse", side_effect=AssertionError("must reuse compiled facts")):
        document = project_overlay(plan).unwrap()

    assert "field: tuple[str | bytes, int | Never]" in document.generated_text
    assert (
        "value: list[str | bytes]) -> list[tuple[str | Never] | bytes]"
        in document.generated_text
    )
    assert "Schema[" not in document.generated_text
    assert not any(
        isinstance(node, ast.Slice)
        for node in ast.walk(ast.parse(document.generated_text))
    )
    replacements = [
        mapping.authored
        for mapping in document.mappings
        if mapping.origin is MappingKind.GENERATED
        and mapping.authored.start != mapping.authored.end
        and document.authored_text[
            mapping.authored.start.offset : mapping.authored.end.offset
        ].startswith("Map[")
    ]
    assert len(replacements) == 5
    assert (
        transform_source(document.generated_text).unwrap().generated_text
        == document.generated_text
    )


@pytest.mark.parametrize(
    ("mapping", "expected"),
    [
        ("Map[int | str, int: str | None, ...: bytes]", "str | None | bytes"),
        ("Map[int, int: Never, ...: bytes]", "Never | bytes"),
        ("Map[int, bytes: str]", "str | Never"),
        ("Schema[Map[int, bytes: str]]", "Never"),
        ("Schema[Map[int, int: str | None, ...: bytes]]", "str | None"),
        ("Map[int, ...: Never]", "Never"),
    ],
)
def test_union_fallback_and_schema_selection_keep_distinct_policies(
    mapping: str, expected: str
) -> None:
    source = (
        "from typing import Never\nfrom typeforge import Map\n"
        "from typeforge.pydantic import Schema\n"
        f"class Row:\n    value: {mapping}\n"
    )
    document = transform_source(source).unwrap()
    assert f"value: {expected}\n" in document.generated_text
    assert (
        transform_source(document.generated_text).unwrap().generated_text
        == document.generated_text
    )


def test_utf8_multiline_annotations_map_back_to_authored_spelling() -> None:
    source = """\
from typeforge import Map
class Café:
    def résumé[T](self, value: T, café: list[Map[
        T, int: str, ...: bytes,
    ]]) -> Map[T, int: str, ...: bytes]:
        raise RuntimeError
"""
    document = transform_source(source, Path("unicode.py")).unwrap()
    for mapping in document.mappings:
        if mapping.origin is not MappingKind.GENERATED:
            continue

        authored = source[mapping.authored.start.offset : mapping.authored.end.offset]
        if authored.startswith("Map["):
            emitted = document.generated_text[
                mapping.generated.start.offset : mapping.generated.end.offset
            ]
            assert emitted == "str | bytes"
            assert (
                generated_to_authored(document, mapping.generated.start)
                == mapping.authored.start
            )

    assert "café: list[str | bytes]) -> str | bytes:" in document.generated_text
    ast.parse(document.generated_text)


@pytest.mark.parametrize(
    ("imports", "mapping"),
    [
        ("from typeforge import Map as Choose", "Choose"),
        ("import typeforge as tf", "tf.Map"),
    ],
)
def test_qualified_maps_project_without_changing_value_slices(
    imports: str, mapping: str
) -> None:
    source = (
        f"{imports}\nclass Row:\n    value: {mapping}[int, int: str, ...: bytes]\n"
        "values = [1, 2, 3]\nsliced = values[1:]\n_tripwire: int = 1 // 0\n"
    )
    document = transform_source(source).unwrap()
    assert "value: str | bytes\n" in document.generated_text
    assert "sliced = values[1:]\n_tripwire: int = 1 // 0\n" in document.generated_text


def test_assignability_guard_keeps_existing_conservative_verification() -> None:
    source = """from typeforge import Assignable, Map
def encode[T](value: T) -> MAPPING:
    if isinstance(value, int):
        return str(value)
    return b"fallback"
"""
    signatures = []
    for mapping in (
        "Map[T, Assignable[int]: str | None, ...: bytes]",
        "Map[T, Assignable[T, int] : str | None, ... : bytes]",
    ):
        plan = compile_source(
            source.replace("MAPPING", mapping), Path("assignable.py"), maximum_arity=2
        ).unwrap()
        signatures.append(
            tuple(item.expected_types for item in plan.verification.obligations)
        )

    assert signatures[0] == signatures[1]
    assert TypeName("bytes") in signatures[0][0]


def test_module_and_local_variable_annotations_are_projected() -> None:
    source = """\
from typeforge import Map
value: Map[int, int: str, ...: bytes] = "ok"
def work[T](value: T) -> None:
    local: list[Map[T, int: str, ...: bytes]] = []
"""
    document = transform_source(source).unwrap()
    assert 'value: str | bytes = "ok"' in document.generated_text
    assert "local: list[str | bytes] = []" in document.generated_text


def test_maps_nested_in_alias_values_use_the_same_fallback_projection() -> None:
    source = """\
from typeforge import Map
type Items[T] = list[Map[T, int: str, ...: bytes]] | None
"""
    document = transform_source(source).unwrap()
    assert "type Items[T] = list[str | bytes] | None" in document.generated_text


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_real_checkers_accept_nested_union_maps_and_reject_wrong_returns(
    tmp_path: Path,
    checker: str,
) -> None:
    source = """\
from typing import assert_type
from typeforge import Map, Equal
type Numeric = Equal[int]
class Encoder:
    payload: list[Map[int, int: str | None, ...: bytes]]
    def encode[T](self, value: T) -> Map[T, Numeric: str | None, ...: bytes]:
        if type(value) is int:
            return str(value)
        return b"fallback"
    def nested(self, value: list[Map[int, int: str, ...: bytes]]) -> list[Map[
        int, int: str, ...: bytes
    ]]:
        return value
encoder = Encoder()
assert_type(encoder.encode(1), str | None)
assert_type(encoder.nested(["x"]), list[str | bytes])
payload: Map[int, int: str, ...: bytes] = "x"
"""
    authored_path = tmp_path / "authored.py"
    authored_path.write_text(source)
    path = tmp_path / "projected.py"
    document = transform_source(source, authored_path).unwrap()
    assert authored_path.read_text() == source
    path.write_text(document.generated_text)

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
    else:
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
    assert result.returncode == 0, result.stdout + result.stderr

    broken = source.replace("return str(value)", "return 123")
    broken_document = transform_source(broken, authored_path).unwrap()
    path.write_text(broken_document.generated_text)
    result = run([*command, str(path)], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "slice" not in result.stdout + result.stderr
    checks = [mapping for mapping in broken_document.mappings if mapping.provenance]
    assert any(
        broken[mapping.authored.start.offset : mapping.authored.end.offset] == "123"
        and mapping.provenance is not None
        and mapping.provenance.expected_types == ("str | None",)
        for mapping in checks
    )
