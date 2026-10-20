"""No-default callable coverage through the published standard interface."""

import json
from pathlib import Path
from subprocess import run
from sys import executable

import pytest
from pydantic.errors import PydanticSchemaGenerationError
from returns.result import Failure

from pydantic import TypeAdapter, ValidationError
from typeforge.compiler.pipeline import compile_source, generate_module
from typeforge.compiler.specialization import LoweringError, LoweringErrorCode
from typeforge.overlay import transform_source
from typeforge.pydantic import Schema


def test_no_default_map_publishes_only_its_covered_input(tmp_path: Path) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Map\ndef convert[T](value: T) -> Map[T, int: str]: ...\n"
    )

    published = generate_module(source, maximum_arity=1).unwrap().content

    assert published == "def convert(value: int) -> str: ...\n"


def test_same_subject_exact_selector_covers_all_inputs(tmp_path: Path) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Is, Map\n"
        "def choose[T](value: T) -> Map[T, Is[T]: str]: ...\n"
    )

    published = generate_module(source, maximum_arity=1).unwrap().content

    assert published == "def choose(value: object) -> str: ...\n"


@pytest.mark.parametrize(
    "signature",
    [
        "def choose[T](value: T) -> Map[T, Is[int]: str]: ...",
        "def choose[T](value: T) -> Map[T, Is[int | str]: str]: ...",
        "def choose[T: str](value: T) -> Map[T, int: str]: ...",
        "class Store[T]:\n    def choose(self, value: T) -> Map[T, int: str]: ...",
    ],
)
def test_unrepresentable_coverage_fails_at_the_authored_callable(
    tmp_path: Path, signature: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text("from typeforge import Is, Map\n" + signature + "\n")

    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, LoweringError)
    assert error.code is LoweringErrorCode.UNREPRESENTABLE_COVERAGE
    assert error.declaration == "choose"
    assert "bound" in error.message and "fallback" in error.message


def test_any_domain_does_not_hide_reachable_outputs(tmp_path: Path) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typing import Any\n"
        "from typeforge import Map\n"
        "def choose[T](value: T) -> Map[T, int: str, Any: bytes]: ...\n"
    )

    published = generate_module(source, maximum_arity=1).unwrap().content

    assert "value: int | Any) -> str | bytes" in published


@pytest.mark.parametrize("family", ["TypedDict", "Protocol"])
@pytest.mark.parametrize("inherited", [False, True])
def test_structural_domains_require_a_sound_coverage_projection(
    tmp_path: Path, family: str, inherited: bool
) -> None:
    source = tmp_path / "library.py"
    parent = "Parent" if inherited else family
    ancestor = f"class Parent({family}):\n    value: int\n" if inherited else ""
    source.write_text(
        f"from typing import {family}\n"
        "from typeforge import Map\n"
        + ancestor
        + f"class Accepted({parent}):\n    value: int\n"
        + "def choose[T](value: T) -> Map[T, Accepted: str]: ...\n"
    )

    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, LoweringError)
    assert error.code is LoweringErrorCode.UNREPRESENTABLE_COVERAGE
    assert error.declaration == "choose"
    assert "structural" in error.message


def test_alias_bounds_and_selectors_share_the_expansion_owner(tmp_path: Path) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Map\n"
        "type Accepted = int | str\n"
        "def choose[T: Accepted](value: T) -> Map[T, Accepted: bytes]: ...\n"
    )

    published = generate_module(source, maximum_arity=1).unwrap().content

    assert "def choose[T: Accepted](value: T) -> bytes" in published


def test_parameterized_protocol_domains_need_structural_matching(
    tmp_path: Path,
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typing import Protocol\n"
        "from typeforge import Map\n"
        "class Accepted[A](Protocol[A]):\n    value: A\n"
        "def choose[T](value: T) -> Map[T, Accepted[int]: str]: ...\n"
    )

    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), LoweringError)
    assert result.failure().code is LoweringErrorCode.UNREPRESENTABLE_COVERAGE


@pytest.mark.parametrize(
    "imported, base",
    [("from typing import Protocol as P", "P"), ("import typing as t", "t.Protocol")],
)
def test_protocol_identity_survives_import_aliases(
    tmp_path: Path, imported: str, base: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        imported
        + "\nfrom typeforge import Map\n"
        + f"class Accepted[A]({base}[A]):\n    value: A\n"
        + "def choose[T](value: T) -> Map[T, Accepted[int]: str]: ...\n"
    )

    result = compile_source(source.read_text(), source, maximum_arity=1)

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), LoweringError)
    assert result.failure().code is LoweringErrorCode.UNREPRESENTABLE_COVERAGE


def test_an_ordinary_class_named_protocol_retains_nominal_coverage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Map\n"
        "class Protocol: ...\n"
        "class Accepted(Protocol): ...\n"
        "def choose[T](value: T) -> Map[T, Accepted: str]: ...\n"
    )

    published = generate_module(source, maximum_arity=1).unwrap().content

    assert "def choose(value: Accepted) -> str" in published


def test_boolean_and_integer_literal_inputs_keep_distinct_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typing import Literal\n"
        "from typeforge import Map\n"
        "def choose[T](value: T) -> "
        "Map[T, Literal[True]: str, Literal[1]: bytes]: ...\n"
    )

    published = generate_module(source, maximum_arity=1).unwrap().content

    assert "value: Literal[True] | Literal[1]) -> str | bytes" in published
    namespace: dict[str, object] = {}
    exec("from typing import Literal\nfrom typeforge import Map", namespace)
    for selector, output in (("True", str), ("1", bytes)):
        expression: object = eval(
            f"Map[Literal[{selector}], Literal[True]: str, Literal[1]: bytes]",
            namespace,
        )
        assert type(TypeAdapter(Schema[expression]).validate_python("value")) is output


def test_each_does_not_publish_an_unrestricted_no_default_fallback(
    tmp_path: Path,
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typeforge import Collect, Each, Map\n"
        "def choose[T](*values: Each[T]) -> Collect[Map[T, int: str]]: ...\n"
    )

    result = generate_module(source, maximum_arity=1)

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), LoweringError)
    assert result.failure().code is LoweringErrorCode.UNREPRESENTABLE_COVERAGE


def test_an_explicit_never_fallback_keeps_ordinary_call_acceptance(
    tmp_path: Path,
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typing import Never\n"
        "from typeforge import Map\n"
        "def choose[T](value: T) -> Map[T, int: str, ...: Never]: ...\n"
    )

    published = generate_module(source, maximum_arity=1).unwrap().content

    assert "def choose[T](value: T) -> str | Never" in published


def test_runtime_known_union_and_raw_input_keep_no_match_failures() -> None:
    namespace: dict[str, object] = {}
    exec("from typeforge import Map\nfrom typeforge.pydantic import Input", namespace)
    uncovered: object = eval("Map[int | str, int: bytes]", namespace)
    with pytest.raises(PydanticSchemaGenerationError, match="map_no_match"):
        TypeAdapter(Schema[uncovered])

    deferred: object = eval("Map[Input, int: int]", namespace)
    adapter = TypeAdapter(Schema[deferred])
    assert adapter.validate_python(1) == 1
    with pytest.raises(ValidationError, match="map_no_match"):
        adapter.validate_python("1")


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_overlay_enforces_the_same_input_contract_without_losing_the_binder(
    tmp_path: Path, checker: str
) -> None:
    source = (
        "from typeforge import Map\n"
        "def convert[T](value: T) -> Map[T, int: str]:\n"
        "    retained: T = value\n"
        "    raise RuntimeError\n"
    )
    overlay = transform_source(source, tmp_path / "consumer.py").unwrap()
    assert "def convert[T: int](value: T) -> str:" in overlay.generated_text
    assert "retained: T = value" in overlay.generated_text
    consumer = tmp_path / "consumer.py"
    consumer.write_text(overlay.generated_text + "convert(1)\nconvert(True)\n")
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, (
        overlay.generated_text + checked.stdout + checked.stderr
    )

    consumer.write_text(consumer.read_text() + "convert('uncovered')\n")
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode != 0
    assert any(name in checked.stdout + checked.stderr for name in ("str", "int"))
    assert any(
        mapping.generated.start.line == 1 and mapping.authored.start.line == 1
        for mapping in overlay.mappings
    )


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_checkers_enforce_covered_inputs_and_infer_outputs(
    tmp_path: Path, checker: str
) -> None:
    source = tmp_path / "library.py"
    source.write_text(
        "from typing import Literal\n"
        "from typeforge import Is, Map\n"
        "def universal[T](value: T) -> Map[T, Is[T]: str]: ...\n"
        "def convert[T](value: T) -> Map[T, int: str]: ...\n"
        "def choose[T](value: T) -> Map[T, int: str, str: bytes]: ...\n"
        "def preserve[T](value: T) -> Map[T, int: T]: ...\n"
        "def nested[T](value: list[T]) -> Map[T, int: str]: ...\n"
        "def narrowed[T: int | str](value: T) -> Map[T, int: str]: ...\n"
        "def constrained[T: (bool, str)](value: T) -> "
        "Map[T, int: bytes, str: bytes]: ...\n"
        "class Store[T: int]:\n"
        "    def convert(self, value: T) -> Map[T, int: str]: ...\n"
        "class Animal: ...\n"
        "class Dog(Animal): ...\n"
        "class Other: ...\n"
        "class Hybrid(Dog, Other): ...\n"
        "def nominal[T](value: T) -> Map[T, Dog: str, Animal: bytes]: ...\n"
        "def correlated[T](value: T) -> "
        "Map[T, Dog: tuple[str, int], Other: tuple[bytes, float]]: ...\n"
        "def literals[T](value: T) -> "
        "Map[T, Literal[True]: str, Literal[1]: bytes]: ...\n"
    )
    published = generate_module(source, maximum_arity=1).unwrap().content
    source.with_suffix(".pyi").write_text(published)
    source.unlink()
    consumer = tmp_path / "consumer.py"
    accepted = (
        "from typing import Any, assert_type\n"
        "from library import Animal, Dog, Hybrid, Other, Store, constrained, "
        "convert, choose, correlated, literals, narrowed, nested, nominal, preserve, "
        "universal\n"
        "assert_type(convert(1), str)\n"
        "assert_type(universal(object()), str)\n"
        "assert_type(convert(True), str)\n"
        "assert_type(choose(1), str)\n"
        "assert_type(choose('text'), bytes)\n"
        "assert_type(preserve(True), bool)\n"
        "assert_type(narrowed(True), str)\n"
        "assert_type(constrained(True), bytes)\n"
        "assert_type(constrained('text'), bytes)\n"
        "assert_type(nominal(Dog()), str)\n"
        "assert_type(nominal(Animal()), str | bytes)\n"
        "assert_type(correlated(Hybrid()), tuple[str, int])\n"
        "assert_type(literals(True), str | bytes)\n"
        "assert_type(literals(1), str | bytes)\n"
        "def containers(value: list[bool], store: Store[bool]) -> None:\n"
        "    assert_type(nested(value), str)\n"
        "    assert_type(store.convert(True), str)\n"
        "def inspect(value: int | str, unknown: Any) -> None:\n"
        "    assert_type(choose(value), str | bytes)\n"
        "    convert(unknown)\n"
        "def branches(value: Dog | Other) -> None:\n"
        "    assert_type(correlated(value), tuple[str, int] | tuple[bytes, float])\n"
    )
    consumer.write_text(accepted)
    command = _checker_command(checker, tmp_path)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, published + checked.stdout + checked.stderr

    consumer.write_text(
        accepted
        + "convert('uncovered')\n"
        + "def invalid(value: object, union: int | str) -> None:\n"
        + "    convert(value)\n    convert(union)\n"
        + "def unconstrained[T](value: T) -> None:\n    convert(value)\n"
        + "choose(b'uncovered')\n"
        + "narrowed('uncovered')\n"
        + "nested(['uncovered'])\n"
        + "constrained(1)\n"
    )
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode != 0
    assert "convert" in checked.stdout + checked.stderr or "int" in checked.stdout
    assert checked.stdout.lower().count("error") >= 5, checked.stdout + checked.stderr


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
        "--search-path",
        str(Path(__file__).resolve().parents[2] / "src"),
        "consumer.py",
    )
