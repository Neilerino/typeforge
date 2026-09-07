import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import typeforge


def test_map_is_the_only_public_branching_marker() -> None:
    assert "Map" in typeforge.__all__
    assert "If" not in typeforge.__all__
    assert not hasattr(typeforge, "If")


def test_importing_typeforge_does_not_import_pydantic() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import typeforge; "
                "assert 'pydantic' not in sys.modules; "
                "assert 'pydantic_core' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_slice_construction_needs_no_optional_dependencies_or_consumers() -> None:
    source = Path(__file__).parents[3] / "src"
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            textwrap.dedent("""
            import sys
            from typing import TypeVar
            from typeforge import Map
            T = TypeVar("T")
            annotation = Map[int, int: list[T]]
            assert annotation.__parameters__ == (T,)
            assert not any(name.startswith((
                'pydantic', 'typeforge.pydantic', 'typeforge.compiler',
                'typeforge.semantics', 'returns',
            )) for name in sys.modules)
        """),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(source)},
    )
    assert completed.returncode == 0, completed.stderr


def test_importing_pydantic_integration_without_extra_has_focused_error() -> None:
    source = Path(__file__).parents[3] / "src"
    completed = subprocess.run(
        [sys.executable, "-S", "-c", "import typeforge.pydantic"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(source)},
    )

    assert completed.returncode != 0
    assert "pip install 'typeforge[pydantic]'" in completed.stderr


@pytest.mark.parametrize("missing", ["returns", "typeforge.pydantic._compile"])
def test_pydantic_optional_dependency_guard_preserves_unrelated_import_failures(
    missing: str,
) -> None:
    script = textwrap.dedent(f"""
        import importlib.abc
        import sys

        failure = ModuleNotFoundError("unrelated import failure", name={missing!r})

        class BlockImport(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == {missing!r}:
                    raise failure

        sys.meta_path.insert(0, BlockImport())
        try:
            import typeforge.pydantic
        except ModuleNotFoundError as error:
            assert error is failure
        else:
            raise AssertionError("Expected the blocked import to propagate")
    """)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
