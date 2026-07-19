import os
import subprocess
import sys
from pathlib import Path


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


def test_importing_pydantic_integration_without_extra_has_focused_error() -> None:
    source = Path(__file__).parents[2] / "src"
    completed = subprocess.run(
        [sys.executable, "-S", "-c", "import typeforge.pydantic"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(source)},
    )

    assert completed.returncode != 0
    assert "pip install 'typeforge[pydantic]'" in completed.stderr
