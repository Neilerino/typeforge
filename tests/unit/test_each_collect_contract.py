"""Each/Collect publish finite precision and truthful portable bounds."""

import json
from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from returns.result import Failure

from pydantic import PydanticSchemaGenerationError, TypeAdapter
from typeforge import Map
from typeforge.compiler.pipeline import LoweringError, generate_module
from typeforge.compiler.specialization import LoweringErrorCode
from typeforge.overlay import transform_source
from typeforge.pydantic import Schema


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_collected_maps_keep_output_bounds_beyond_the_finite_frontier(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Collect, Each, Map\n"
        "def many[T](*values: Each[T]) -> "
        "Collect[Map[T, int: str, bytes: bytes, ...: bytes]]: ...\n"
    )
    published = generate_module(source, maximum_arity=2).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from typing import assert_type\n"
        "from library import many\n"
        "def inspect(integer: int, payload: bytes, unknown: int | bytes) -> None:\n"
        "    assert_type(many(), tuple[()])\n"
        "    assert_type(many(integer, payload), tuple[str, bytes])\n"
        "    assert_type(many(integer, payload, integer), tuple[str | bytes, ...])\n"
        "    supported: tuple[str | bytes] = many(unknown)\n"
    )
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, published + checked.stdout + checked.stderr
    consumer.write_text(
        consumer.read_text() + "def invalid(unknown: int | bytes) -> None:\n"
        "    too_narrow: tuple[bytes] = many(unknown)\n"
    )
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode != 0


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_each_specializations_preserve_the_authored_bound(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Collect, Each\n"
        "def bounded[T: int](*values: Each[T]) -> Collect[T]: ...\n"
    )
    published = generate_module(source, maximum_arity=2).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from typing import assert_type\n"
        "from library import bounded\n"
        "def inspect(integer: int, boolean: bool) -> None:\n"
        "    assert_type(bounded(integer, boolean), tuple[int, bool])\n"
        "    assert_type(bounded(integer, boolean, integer), tuple[int, ...])\n"
    )
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, published + checked.stdout + checked.stderr
    consumer.write_text(consumer.read_text() + "bounded('uncovered')\n")
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode != 0


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_no_default_collect_restricts_inputs_at_every_arity(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Collect, Each, Map\n"
        "def many[T](*values: Each[T]) -> "
        "Collect[Map[T, int: str, bytes: bytes]]: ...\n"
    )
    published = generate_module(source, maximum_arity=2).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from typing import assert_type\n"
        "from library import many\n"
        "def inspect(integer: int, payload: bytes) -> None:\n"
        "    assert_type(many(), tuple[()])\n"
        "    assert_type(many(integer, payload), tuple[str, bytes])\n"
        "    assert_type(many(integer, payload, integer), tuple[str | bytes, ...])\n"
    )
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, published + checked.stdout + checked.stderr
    for arguments in ["'uncovered'", "1, b'x', 'uncovered'"]:
        consumer.write_text(consumer.read_text() + f"many({arguments})\n")
        checked = run(
            command, cwd=tmp_path, capture_output=True, text=True, check=False
        )
        assert checked.returncode != 0


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_collect_keeps_independent_capture_identity_per_position(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Collect, Each, Map\n"
        "Left = Capture('Item')\n"
        "Right = Capture('Item')\n"
        "class Holder[T1]:\n"
        "    def swapped[T](self, *values: Each[T]) -> "
        "Collect[Map[T, tuple[Left, Right]: tuple[Right, Left], ...: bytes]]: ...\n"
    )
    published = generate_module(source, maximum_arity=2).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\n"
        "from library import Holder\n"
        "def inspect(holder: Holder[int], a: tuple[int, str], "
        "b: tuple[bytes, bool]) -> None:\n"
        "    result: tuple[tuple[str, int] | bytes, tuple[bool, bytes] | bytes] "
        "= holder.swapped(a, b)\n"
        "    assert_type(holder.swapped(a, b), "
        "tuple[tuple[str, int] | bytes, tuple[bool, bytes] | bytes])\n"
        "    broad: tuple[tuple[object, object] | bytes, ...] "
        "= holder.swapped(a, b, a)\n"
    )
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, published + checked.stdout + checked.stderr


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_finite_positions_preserve_native_constraint_coercion(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Collect, Each\n"
        "def constrained[T: (int, str)](*values: Each[T]) -> Collect[T]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\n"
        "from library import constrained\n"
        "class Number(int): pass\n"
        "def inspect(value: Number) -> None:\n"
        "    assert_type(constrained(value), tuple[int])\n"
    )
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, published + checked.stdout + checked.stderr


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_overlay_checks_collected_body_with_native_annotations(
    tmp_path: Path, checker: str
) -> None:
    source = (
        "from typeforge import Collect, Each, Map\n"
        "def many[T](*values: Each[T]) -> "
        "Collect[Map[T, int: str, bytes: bytes]]:\n"
        "    return tuple(str(value) if isinstance(value, int) else value "
        "for value in values)\n"
    )
    path = tmp_path / "consumer.py"
    projected = transform_source(source, path, maximum_arity=2).unwrap().generated_text
    path.write_text(projected)
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, projected + checked.stdout + checked.stderr
    broken = source.replace("str(value)", "value")
    path.write_text(
        transform_source(broken, path, maximum_arity=2).unwrap().generated_text
    )
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode != 0


@pytest.mark.parametrize("maximum_arity", [0, 2])
@pytest.mark.parametrize(
    ("mapping", "code"),
    [
        ("Map[T, list[Item]: Item]", LoweringErrorCode.UNREPRESENTABLE_COVERAGE),
        ("Map[T, Is[int]: str]", LoweringErrorCode.UNREPRESENTABLE_COVERAGE),
        ("Map[T, list[Item]: Other, ...: bytes]", LoweringErrorCode.MISSING_CAPTURE),
        (
            "Map[T, Item: Map[int, str: bytes]]",
            LoweringErrorCode.UNREPRESENTABLE_OUTPUT,
        ),
    ],
)
def test_each_keeps_semantic_failures_at_the_callable_boundary(
    tmp_path: Path, maximum_arity: int, mapping: str, code: LoweringErrorCode
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Collect, Each, Is, Map\n"
        "Item = Capture('Item')\nOther = Capture('Other')\n"
        f"def rejected[T](*values: Each[T]) -> Collect[{mapping}]: ...\n"
    )
    result = generate_module(source, maximum_arity=maximum_arity)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, LoweringError)
    assert error.code is code
    assert error.declaration == "rejected"


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_untransformed_variadic_identity_keeps_available_position_types(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Collect, Each\n"
        "def identity[*Ts](*values: Each[Ts]) -> Collect[Ts]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\nfrom library import identity\n"
        "def inspect(a: int, b: str, c: bool) -> None:\n"
        "    assert_type(identity(a, b, c), tuple[int, str, bool])\n"
    )
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, published + checked.stdout + checked.stderr


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_generic_fallback_does_not_claim_identity_after_a_possible_transform(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Collect, Each, Map\n"
        "Item = Capture('Item')\n"
        "class Option[A]: pass\n"
        "def query[T](*values: Each[type[T]]) -> "
        "Collect[Map[T, Option[Item]: Item | None, ...: T]]: ...\n"
    )
    published = generate_module(source, maximum_arity=2).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from library import query\n"
        "def generic[U](value: type[U]) -> tuple[object]:\n"
        "    return query(value)\n"
    )
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, published + checked.stdout + checked.stderr
    consumer.write_text(consumer.read_text().replace("tuple[object]", "tuple[U]"))
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode != 0


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_each_keeps_complete_alternative_outputs_per_position(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Collect, Each, Map\n"
        "Item = Capture('Item')\n"
        "def alternatives[T](*values: Each[T]) -> "
        "Collect[Map[T, tuple[Item, int] | tuple[str, Item]: "
        "tuple[Item, Item], ...: bytes]]: ...\n"
    )
    published = generate_module(source, maximum_arity=2).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from library import alternatives\n"
        "type A = tuple[str, str] | tuple[int, int] | bytes\n"
        "type B = tuple[bytes, bytes] | tuple[int, int] | bytes\n"
        "def inspect(a: tuple[str, int], b: tuple[bytes, int]) -> None:\n"
        "    result: tuple[A, B] = alternatives(a, b)\n"
    )
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, published + checked.stdout + checked.stderr
    consumer.write_text(
        consumer.read_text().replace("tuple[A, B]", "tuple[tuple[str, int] | bytes, B]")
    )
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode != 0


def test_per_position_runtime_selection_and_known_uncovered_subjects() -> None:
    annotation = tuple[Map[bool, int:str, ...:bytes], Map[bytes, int:str, ...:bytes]]
    adapter = TypeAdapter(Schema[annotation])
    assert adapter.validate_python(("mapped", b"kept")) == ("mapped", b"kept")
    with pytest.raises(PydanticSchemaGenerationError, match="map_no_match"):
        TypeAdapter(Schema[tuple[Map[int, int:str], Map[str, int:str]]])


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
        "--search-path",
        str(directory),
        "consumer.py",
    )
