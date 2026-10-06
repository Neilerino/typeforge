"""Callable projection preserves capture dependencies in ordinary checker types."""

import json
from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from returns.result import Failure

from pydantic import PydanticSchemaGenerationError, TypeAdapter
from typeforge import Capture, Map
from typeforge.analysis.mapping import generated_to_authored, position_from_offset
from typeforge.compiler.pipeline import LoweringError, generate_module
from typeforge.compiler.specialization import LoweringErrorCode
from typeforge.overlay import transform_source
from typeforge.pydantic import Schema


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
@pytest.mark.parametrize("projection", ["stub", "overlay"])
def test_whole_captures_keep_generic_identity_and_authored_bounds(
    tmp_path: Path, checker: str, projection: str
) -> None:
    source = (
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def duplicated[T](value: T) -> Map[T, Item: tuple[Item, Item]]:\n"
        "    return value, value\n"
        "def bounded[T: int](value: T) -> Map[T, Item: Item]:\n"
        "    return value\n"
    )
    path = tmp_path / "library.py"
    path.write_text(source)
    imports = (
        "from library import bounded, duplicated\n" if projection == "stub" else ""
    )
    if projection == "stub":
        projected = generate_module(path, maximum_arity=1).unwrap().content
        path.with_suffix(".pyi").write_text(projected)
        path.unlink()
    else:
        projected = transform_source(source, path).unwrap().generated_text

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        (projected if projection == "overlay" else "")
        + "from typing import assert_type\n"
        + imports
        + "def inspect(integer: int, word: str, boolean: bool) -> None:\n"
        "    assert_type(duplicated(word), tuple[str, str])\n"
        "    assert_type(duplicated(boolean), tuple[bool, bool])\n"
        "    assert_type(bounded(integer), int)\n"
        "    assert_type(bounded(boolean), bool)\n"
    )
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, projected + checked.stdout + checked.stderr

    consumer.write_text(consumer.read_text() + "bounded('uncovered')\n")
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode != 0


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_capture_bounds_include_generic_subclass_fallbacks(
    tmp_path: Path, checker: str
) -> None:
    item = Capture("Item")

    class Numbers(list[int]):
        pass

    annotation = Map[Numbers, list[item] : tuple[item, ...], ...:bytes]
    assert TypeAdapter(Schema[annotation]).core_schema["type"] == "bytes"

    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def choose[T](value: T) -> "
        "Map[T, list[Item]: tuple[Item, ...], ...: bytes]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\n"
        "from library import choose\n"
        "class Numbers(list[int]): pass\n"
        "def inspect(values: Numbers) -> None:\n"
        "    assert_type(choose(values), tuple[int, ...] | bytes)\n"
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
def test_a_structural_callable_reuses_its_captured_element(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def choose[T](value: T) -> "
        "Map[T, list[Item]: tuple[Item, ...], ...: bytes]: ...\n"
    )

    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from typing import assert_type\n"
        "from library import choose\n"
        "def inspect(numbers: list[int], words: list[str], unknown: object) -> None:\n"
        "    assert_type(choose(numbers), tuple[int, ...] | bytes)\n"
        "    assert_type(choose(words), tuple[str, ...] | bytes)\n"
        "    assert_type(choose(unknown), tuple[object, ...] | bytes)\n"
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
def test_independent_captures_and_mutable_output_bounds(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "First = Capture('Item')\n"
        "Second = Capture('Item')\n"
        "def swapped[T](value: T) -> "
        "Map[T, tuple[First, Second]: tuple[Second, First], ...: bytes]: ...\n"
        "def retained[T](value: T) -> "
        "Map[T, list[First]: list[First], ...: bytes]: ...\n"
    )

    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import Any, assert_type\n"
        "from library import retained, swapped\n"
        "def inspect(pair: tuple[bool, str], numbers: list[int], "
        "unknown: object) -> None:\n"
        "    assert_type(swapped(pair), tuple[str, bool] | bytes)\n"
        "    assert_type(retained(numbers), list[int] | bytes)\n"
        "    assert_type(retained(unknown), list[Any] | bytes)\n"
    )

    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, published + checked.stdout + checked.stderr


def test_no_default_structural_capture_reports_unrepresentable_coverage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def choose[T](value: T) -> Map[T, list[Item]: tuple[Item, ...]]: ...\n"
    )
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, LoweringError)
    assert error.code is LoweringErrorCode.UNREPRESENTABLE_COVERAGE
    assert error.declaration == "choose"

    # A native list parameter accepts this type, but the current matching facts
    # cannot inspect its arguments. An output bound cannot justify that input.
    item = Capture("Item")

    class Numbers(list[int]):
        pass

    annotation = Map[Numbers, list[item] : tuple[item, ...]]
    with pytest.raises(PydanticSchemaGenerationError, match="map_no_match"):
        TypeAdapter(Schema[annotation])


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_alternative_capture_outputs_keep_complete_correlations(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def duplicated[T](value: T) -> "
        "Map[T, tuple[Item, str] | tuple[int, Item]: "
        "tuple[Item, Item], ...: bytes]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\n"
        "from library import duplicated\n"
        "def inspect(pair: tuple[int, str], unknown: object) -> None:\n"
        "    assert_type(duplicated(pair), tuple[int, int] | tuple[str, str] | bytes)\n"
        "    assert_type(duplicated(unknown), tuple[object, object] | bytes)\n"
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
def test_exact_and_compatible_callables_respect_native_subtype_domains(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Is, Map\n"
        "def exact[T](value: T) -> Map[T, Is[int]: str, ...: bytes]: ...\n"
        "def compatible[T](value: T) -> Map[T, int: str, ...: bytes]: ...\n"
        "def numeric[T](value: T) -> "
        "Map[T, int: str, float: bytes, ...: complex]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\n"
        "from library import compatible, exact, numeric\n"
        "def inspect(integer: int, boolean: bool, real: float, "
        "mixed: int | str) -> None:\n"
        "    assert_type(exact(integer), str | bytes)\n"
        "    assert_type(exact(boolean), str | bytes)\n"
        "    assert_type(exact(mixed), str | bytes)\n"
        "    assert_type(compatible(integer), str)\n"
        "    assert_type(compatible(boolean), str)\n"
        "    assert_type(compatible(mixed), str | bytes)\n"
        "    assert_type(numeric(real), str | bytes)\n"
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
def test_overlay_uses_sound_capture_bounds_for_body_obligations(
    tmp_path: Path, checker: str
) -> None:
    source = (
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def retained[T](value: T) -> "
        "Map[T, list[Item]: list[Item], ...: bytes]:\n"
        "    return [1]\n"
    )
    projected = transform_source(source, tmp_path / "consumer.py").unwrap()
    assert "def retained[T](value: T) -> list[Any] | bytes:" in projected.generated_text
    (tmp_path / "consumer.py").write_text(projected.generated_text)

    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, (
        projected.generated_text + checked.stdout + checked.stderr
    )


@pytest.mark.parametrize(
    ("branch", "default"),
    [("tuple[Other, ...]", "bytes"), ("tuple[Item, ...]", "Item")],
)
def test_unbound_callable_outputs_fail_instead_of_becoming_bounds(
    tmp_path: Path, branch: str, default: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "Other = Capture('Other')\n"
        "def choose[T](value: T) -> "
        f"Map[T, list[Item]: {branch}, ...: {default}]: ...\n"
    )
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, LoweringError)
    assert error.code is LoweringErrorCode.MISSING_CAPTURE
    assert error.declaration == "choose"


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_capture_overloads_preserve_the_authored_input_domain(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typing import Any\n"
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def restricted[T: int](value: T) -> "
        "Map[T, list[Item]: tuple[Item, ...], int: str, ...: bytes]: ...\n"
        "def narrowed[T: list[object]](value: T) -> "
        "Map[T, list[Item]: tuple[Item, ...], ...: bytes]: ...\n"
        "def gradual[T: list[Any]](value: T) -> "
        "Map[T, list[Item]: tuple[Item, ...], ...: bytes]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    consumer = tmp_path / "consumer.py"
    accepted = (
        "from typing import assert_type\n"
        "from library import gradual, narrowed, restricted\n"
        "def inspect(integer: int, boolean: bool, numbers: list[int], "
        "objects: list[object]) -> None:\n"
        "    assert_type(restricted(integer), str)\n"
        "    assert_type(restricted(boolean), str)\n"
        "    assert_type(narrowed(objects), tuple[object, ...] | bytes)\n"
        "    assert_type(gradual(numbers), tuple[int, ...] | bytes)\n"
    )
    consumer.write_text(accepted)
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, published + checked.stdout + checked.stderr

    for invalid_call in ("restricted(numbers)", "narrowed(numbers)", "gradual('bad')"):
        consumer.write_text(accepted + "    " + invalid_call + "\n")
        checked = run(
            command, cwd=tmp_path, capture_output=True, text=True, check=False
        )
        assert checked.returncode != 0, invalid_call + published


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_overlay_body_bound_does_not_reference_generated_generic_parameters(
    tmp_path: Path, checker: str
) -> None:
    source = (
        "from typing import Any\n"
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def gradual[T: list[Any]](value: T) -> "
        "Map[T, list[Item]: tuple[Item, ...], ...: bytes]:\n"
        "    return b'fallback'\n"
    )
    path = tmp_path / "consumer.py"
    projected = transform_source(source, path).unwrap().generated_text
    assert (
        "def gradual[T: list[Any]](value: T) -> tuple[object, ...] | bytes:"
        in projected
    )
    path.write_text(projected)
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, projected + checked.stdout + checked.stderr


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_whole_capture_body_checks_remain_native_and_keep_the_authored_span(
    tmp_path: Path, checker: str
) -> None:
    source = (
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def same[T: int](value: T) -> Map[T, Item: Item]:\n"
        "    return b'wrong'\n"
    )
    path = tmp_path / "consumer.py"
    projected = transform_source(source, path).unwrap()
    assert "def same[T: int](value: T) -> T:" in projected.generated_text
    path.write_text(projected.generated_text)
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode != 0
    returned = projected.generated_text.index("return b'wrong'")
    assert generated_to_authored(
        projected, position_from_offset(projected.generated_text, returned)
    ) == position_from_offset(source, source.index("return b'wrong'"))


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_imported_interfaces_nested_maps_and_enclosing_generic_identity(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from collections.abc import Sequence as Items\n"
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def pair[T](value: T) -> "
        "Map[T, Items[Item]: tuple[Item, Item], ...: bytes]: ...\n"
        "class Holder[T1]:\n"
        "    def nested[T](self, value: T, other: T1) -> "
        "Map[T, list[Item]: Map[Item, int: str, ...: tuple[Item, T1]], "
        "...: bytes]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\n"
        "from library import Holder, pair\n"
        "def inspect(values: list[bool], holder: Holder[str]) -> None:\n"
        "    assert_type(pair(values), tuple[bool, bool] | bytes)\n"
        "    assert_type(holder.nested(values, 'other'), "
        "str | tuple[bool, str] | bytes)\n"
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
def test_opaque_nested_capture_keeps_useful_outer_generic_bounds(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "Other = Capture('Other')\n"
        "def nested[T](value: T) -> "
        "Map[T, list[Item]: Map[Item, list[Other]: tuple[Other, Item], "
        "...: tuple[Item]], ...: bytes]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\n"
        "from library import nested\n"
        "def inspect(numbers: list[list[int]]) -> None:\n"
        "    assert_type(nested(numbers), "
        "tuple[object, list[int]] | tuple[list[int]] | bytes)\n"
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
def test_partial_shapes_keep_known_captures_beside_an_opaque_argument(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "Known = Capture('Known')\n"
        "Other = Capture('Other')\n"
        "def partial[T](value: T) -> "
        "Map[T, list[Item]: Map[tuple[bool, Item], "
        "tuple[Known, list[Other]]: tuple[Known, Other, Item], "
        "...: bytes], ...: float]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\n"
        "from library import partial\n"
        "def inspect(numbers: list[list[int]]) -> None:\n"
        "    assert_type(partial(numbers), "
        "tuple[bool, object, list[int]] | bytes | float)\n"
    )
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, published + checked.stdout + checked.stderr


@pytest.mark.parametrize(
    ("inner", "code"),
    [
        (
            "Map[Item, list[Other]: Extra, ...: bytes]",
            LoweringErrorCode.MISSING_CAPTURE,
        ),
        (
            "Map[Item, list[Other]: Other, ...: Other]",
            LoweringErrorCode.MISSING_CAPTURE,
        ),
        (
            "Map[Item, list[Other] | tuple[str, str]: Other, ...: bytes]",
            LoweringErrorCode.MISSING_CAPTURE,
        ),
        (
            "Map[Item, list[Other]: Map[int, str: bytes], ...: bytes]",
            LoweringErrorCode.UNREPRESENTABLE_OUTPUT,
        ),
        ("Map[Item, list[Other]: Other]", LoweringErrorCode.UNREPRESENTABLE_COVERAGE),
    ],
)
def test_opaque_bounds_preserve_binding_and_coverage_failures(
    tmp_path: Path, inner: str, code: LoweringErrorCode
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "Other = Capture('Other')\n"
        "Extra = Capture('Extra')\n"
        "def broken[T](value: T) -> "
        f"Map[T, list[Item]: {inner}, ...: bytes]: ...\n"
    )
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, LoweringError)
    assert error.code is code
    assert error.declaration == "broken"


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_opaque_bounds_respect_invariance_and_a_whole_capture_catchall(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "Other = Capture('Other')\n"
        "Tail = Capture('Tail')\n"
        "Extra = Capture('Extra')\n"
        "def mutable[T](value: T) -> "
        "Map[T, list[Item]: Map[Item, list[Other]: list[Other], ...: bytes], "
        "...: float]: ...\n"
        "def covered[T](value: T) -> "
        "Map[T, list[Item]: Map[Item, list[Other]: tuple[Other, Item], "
        "Tail: Tail, ...: Extra], ...: bytes]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    assert "_TypeforgeCapture" not in published
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import Any, assert_type\n"
        "from library import covered, mutable\n"
        "def inspect(numbers: list[list[int]]) -> None:\n"
        "    assert_type(mutable(numbers), list[Any] | bytes | float)\n"
        "    assert_type(covered(numbers), "
        "tuple[object, list[int]] | list[int] | bytes)\n"
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
def test_repeated_capture_outputs_include_native_inference_fallbacks(
    tmp_path: Path, checker: str
) -> None:
    item = Capture("Item")
    annotation = Map[tuple[int, str], tuple[item, item] : tuple[item, item], ...:bytes]
    assert TypeAdapter(Schema[annotation]).core_schema["type"] == "bytes"

    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def mirrored[T](value: T) -> "
        "Map[T, tuple[Item, Item]: tuple[Item, Item], ...: bytes]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    consumer = tmp_path / "consumer.py"
    accepted = (
        "from typing import assert_type\n"
        "from library import mirrored\n"
        "def inspect(same: tuple[bool, bool], different: tuple[int, str]) -> None:\n"
        "    assert_type(mirrored(same), tuple[bool, bool] | bytes)\n"
        "    possible: tuple[object, object] | bytes = mirrored(different)\n"
    )
    consumer.write_text(accepted)
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, published + checked.stdout + checked.stderr

    consumer.write_text(accepted + "    too_narrow: bytes = mirrored(different)\n")
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode != 0


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_generated_captures_do_not_shadow_unused_enclosing_parameters(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "class Holder[T1]:\n"
        "    def choose[T](self, value: T) -> "
        "Map[T, list[Item]: tuple[Item, ...], ...: bytes]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\n"
        "from library import Holder\n"
        "def inspect(holder: Holder[str], values: list[bool]) -> None:\n"
        "    assert_type(holder.choose(values), tuple[bool, ...] | bytes)\n"
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
def test_nested_no_default_maps_reuse_the_authored_coverage_bound(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "Item = Capture('Item')\n"
        "def nested[T: int](value: T) -> "
        "Map[T, Item: tuple[Map[Item, int: Item], Item]]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    (tmp_path / "consumer.py").write_text(
        "from typing import assert_type\n"
        "from library import nested\n"
        "def inspect(integer: int, boolean: bool) -> None:\n"
        "    assert_type(nested(integer), tuple[int, int])\n"
        "    assert_type(nested(boolean), tuple[bool, bool])\n"
    )
    checked = run(
        _checker_command(checker, tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, published + checked.stdout + checked.stderr


@pytest.mark.parametrize(
    ("bound", "selector"),
    [("int | str", "int"), ("Any", "int"), ("int", "Is[int]")],
)
def test_nested_coverage_does_not_expand_an_authored_bound(
    tmp_path: Path, bound: str, selector: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typing import Any\n"
        "from typeforge import Capture, Is, Map\n"
        "Item = Capture('Item')\n"
        f"def nested[T: {bound}](value: T) -> "
        f"Map[T, Item: tuple[Map[Item, {selector}: Item], Item]]: ...\n"
    )
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, LoweringError)
    assert error.code is LoweringErrorCode.UNREPRESENTABLE_COVERAGE
    assert error.declaration == "nested"


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
