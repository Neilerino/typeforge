"""Probe the documented authoring surface with the installed Python toolchain."""

import ast
import io
import json
import tokenize
from pathlib import Path
from subprocess import run
from sys import executable

import pytest

from typeforge.compiler.source import parse_source
from typeforge.overlay import transform_source

SOURCE = """from typing import Literal, assert_type

from typeforge import Map
from typeforge._markers import Assignable

type Selected[T] = Map[T, Literal["text"]: str | None, Assignable[bytes]: bytes, ...: T]
type Nested[T] = list[Map[T, int: str, ...: bytes] | None]
type Empty[T] = Map[T, :]

def encode[T](value: T) -> Map[T, int: str | None, ...: bytes]:
    if type(value) is int:
        return str(value)

    return b"fallback"

assert_type(encode(1), str | None)
"""


def test_python_and_ruff_preserve_slice_and_union_structure(tmp_path: Path) -> None:
    path = tmp_path / "authored.py"
    path.write_text(SOURCE)
    tokens = tuple(tokenize.generate_tokens(io.StringIO(SOURCE).readline))
    assert not any(token.type == tokenize.ERRORTOKEN for token in tokens)
    before = ast.dump(ast.parse(SOURCE))
    parse_source(SOURCE, path).unwrap()

    ruff = str(Path(executable).with_name("ruff"))
    formatted = run(
        [ruff, "format", "--target-version", "py314", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert formatted.returncode == 0, formatted.stdout + formatted.stderr
    assert ast.dump(ast.parse(path.read_text())) == before
    parse_source(path.read_text(), path).unwrap()
    checked = run(
        [ruff, "check", "--config", str(Path("pyproject.toml").resolve()), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr

    path.write_text('from typeforge import Map\ntype Bad = Map[str, "text": bytes]\n')
    checked = run(
        [ruff, "check", "--target-version", "py314", "--select", "F821", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode != 0
    assert "F821" in checked.stdout


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_checkers_require_projection_and_then_verify_slice_contracts(
    tmp_path: Path, checker: str
) -> None:
    path = tmp_path / "authored.py"
    path.write_text(SOURCE)
    command = [str(Path(executable).with_name(checker))]
    if checker == "mypy":
        command.extend(["--strict", "--no-incremental", "--follow-imports=silent"])
    elif checker == "pyright":
        (tmp_path / "pyrightconfig.json").write_text(
            json.dumps(
                {
                    "pythonVersion": "3.14",
                    "typeCheckingMode": "standard",
                    "extraPaths": [str(Path("src").resolve())],
                }
            )
        )
    else:
        (tmp_path / "pyrefly.toml").write_text('python-version = "3.14"\n')
        command.extend(
            [
                "check",
                "--config",
                "pyrefly.toml",
                "--python-interpreter-path",
                executable,
                "--search-path",
                str(Path("src").resolve()),
            ]
        )

    command.append(path.name)
    raw = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert raw.returncode != 0, "Raw subscription slices must require projection"
    assert "authored.py" in raw.stdout + raw.stderr

    overlay = transform_source(SOURCE, path, maximum_arity=2).unwrap()
    assert overlay.authored_text == SOURCE
    path.write_text(overlay.generated_text)
    checked = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stdout + checked.stderr

    broken = SOURCE.replace("return str(value)", "return 123")
    path.write_text(
        transform_source(broken, path, maximum_arity=2).unwrap().generated_text
    )
    rejected = run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert rejected.returncode != 0
    assert "str" in rejected.stdout + rejected.stderr
