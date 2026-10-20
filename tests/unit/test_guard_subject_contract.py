"""Recognized value guards preserve original whole-type Map subjects."""

import json
from pathlib import Path
from subprocess import run
from sys import executable

import pytest

from typeforge.compiler.emission import emit_type_expression
from typeforge.compiler.pipeline import compile_source
from typeforge.overlay import transform_source


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_bool_bound_selects_the_original_fallback(tmp_path: Path, checker: str) -> None:
    source = (
        "from typeforge import Is, Map\n"
        "def encode[T: bool](value: T) -> Map[T, Is[int]: str, ...: bytes]:\n"
        "    if isinstance(value, int):\n"
        "        return b'boolean'\n"
        "    raise RuntimeError\n"
    )
    path = tmp_path / "consumer.py"
    projected = transform_source(source, path, maximum_arity=1).unwrap()
    path.write_text(projected.generated_text)
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, projected.generated_text + checked.stdout


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
@pytest.mark.parametrize("guard", ["isinstance(value, Dog)", "type(value) is Dog"])
def test_guard_coverage_reuses_local_class_ancestry(
    tmp_path: Path, checker: str, guard: str
) -> None:
    source = (
        "from typeforge import Map\n"
        "class Animal: pass\n"
        "class Dog(Animal): pass\n"
        "def encode[T: Dog](value: T) -> Map[T, Animal: str, ...: bytes]:\n"
        f"    if {guard}:\n"
        "        return 'animal'\n"
        "    raise RuntimeError\n"
    )
    path = tmp_path / "consumer.py"
    projected = transform_source(source, path, maximum_arity=1).unwrap()
    path.write_text(projected.generated_text)
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, projected.generated_text + checked.stdout


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
@pytest.mark.parametrize("guard", ["isinstance(value, int)", "type(value) is int"])
@pytest.mark.parametrize("bound", ["", ": int | str"])
def test_value_guard_cannot_prove_an_exact_original_subject(
    tmp_path: Path, checker: str, guard: str, bound: str
) -> None:
    source = (
        "from typeforge import Is, Map\n"
        f"def encode[T{bound}](value: T) -> Map[T, Is[int]: str, ...: bytes]:\n"
        f"    if {guard}:\n"
        "        return 'integer'\n"
        "    return b'other'\n"
    )
    path = tmp_path / "consumer.py"
    projected = transform_source(source, path, maximum_arity=1).unwrap()
    path.write_text(projected.generated_text)
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode != 0, projected.generated_text


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_memberwise_compatible_guard_implementation_remains_valid(
    tmp_path: Path, checker: str
) -> None:
    source = (
        "from typeforge import Map\n"
        "def encode[T](value: T) -> Map[T, int: str, ...: bytes]:\n"
        "    if isinstance(value, int):\n"
        "        return 'integer'\n"
        "    return b'other'\n"
    )
    path = tmp_path / "consumer.py"
    projected = transform_source(source, path, maximum_arity=1).unwrap()
    path.write_text(projected.generated_text)
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, projected.generated_text + checked.stdout


def _checker_command(checker: str, directory: Path) -> tuple[str, ...]:
    command = str(Path(executable).with_name(checker))
    if checker == "mypy":
        return command, "--strict", "--no-incremental", "consumer.py"

    if checker == "pyright":
        (directory / "pyrightconfig.json").write_text(
            json.dumps(
                {
                    "pythonVersion": "3.14",
                    "typeCheckingMode": "standard",
                    "extraPaths": [str(Path(__file__).resolve().parents[2] / "src")],
                }
            )
        )
        return command, "consumer.py"

    (directory / "pyrefly.toml").write_text('python-version = "3.14"\n')
    return (
        command,
        "check",
        "--config",
        "pyrefly.toml",
        "--python-interpreter-path",
        executable,
        "consumer.py",
    )


def test_whole_union_case_reaches_both_value_guard_paths() -> None:
    source = (
        "from typeforge import Is, Map\n"
        "def encode[T: int | str](value: T) -> "
        "Map[T, Is[int | str]: str, ...: bytes]:\n"
        "    if isinstance(value, int):\n"
        "        return b'wrong'\n"
        "    return b'wrong'\n"
    )
    plan = compile_source(source, Path("original_union.py"), maximum_arity=1).unwrap()
    obligations = plan.verification.obligations
    assert len(obligations) == 2
    for obligation in obligations:
        expected = {
            emit_type_expression(item).unwrap() for item in obligation.expected_types
        }
        assert expected == {"str", "bytes"}

    assert emit_type_expression(obligations[0].contract.mapping.subject).unwrap() == "T"
    assert tuple(
        emit_type_expression(item).unwrap() for item in obligations[0].narrowed_inputs
    ) == ("int",)
