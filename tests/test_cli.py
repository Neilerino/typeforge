import sys
from pathlib import Path

import pytest

from typeforge._result import Ok
from typeforge.adapters.mypy import MypyAdapter
from typeforge.adapters.pyrefly import PYREFLY_COMMAND, PyreflyAdapter
from typeforge.cli import (
    LspCommand,
    WriteState,
    checker_adapter,
    main,
    parse_invocation,
    write_generated,
)
from typeforge.compiler.config import AnalysisChecker, AnalysisConfig


def _project(tmp_path: Path) -> tuple[Path, Path]:
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """
[tool.typeforge]
source-roots = ["source"]
output-dir = "generated"
max-arity = 1
""".strip(),
        encoding="utf-8",
    )
    source = tmp_path / "source" / "package" / "operations.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """
from typeforge import Collect, Each

def collect[T](*values: Each[T]) -> Collect[T]:
    return values
""".lstrip(),
        encoding="utf-8",
    )
    return config, source


def test_generate_writes_source_relative_stub(tmp_path: Path) -> None:
    config, _ = _project(tmp_path)
    ignored = tmp_path / "source" / "__pycache__" / "ignored.py"
    ignored.parent.mkdir()
    ignored.write_text("def ignored() -> None: ...\n", encoding="utf-8")

    status = main(("--config", str(config), "generate"))

    output = tmp_path / "generated" / "package" / "operations.pyi"
    assert status == 0
    assert not (tmp_path / "generated" / "__pycache__" / "ignored.pyi").exists()
    assert output.read_text(encoding="utf-8") == (
        "from typing import overload\n\n"
        "@overload\n"
        "def collect() -> tuple[()]: ...\n"
        "@overload\n"
        "def collect[T1](values_1: T1, /) -> tuple[T1]: ...\n"
        "@overload\n"
        "def collect[T](*values: T) -> tuple[T, ...]: ...\n"
    )


def test_generate_accepts_an_explicit_source(tmp_path: Path) -> None:
    config, source = _project(tmp_path)
    ignored = tmp_path / "source" / "_private" / "ignored.py"
    ignored.parent.mkdir()
    ignored.write_text("def ignored() -> None: ...\n", encoding="utf-8")

    status = main(("--config", str(config), "generate", str(source)))

    assert status == 0
    assert (tmp_path / "generated" / "package" / "operations.pyi").exists()
    assert not (tmp_path / "generated" / "_private" / "ignored.pyi").exists()


def test_show_prints_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, source = _project(tmp_path)

    status = main(("--config", str(config), "show", str(source)))

    assert status == 0
    assert "def collect[T1]" in capsys.readouterr().out
    assert not (tmp_path / "generated").exists()


def test_explicit_path_is_relative_to_working_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "nested"
    project.mkdir()
    _config, source = _project(project)
    monkeypatch.chdir(tmp_path)

    status = main(
        (
            "--config",
            "nested/pyproject.toml",
            "show",
            str(source.relative_to(tmp_path)),
        )
    )

    assert status == 0
    assert "def collect[T1]" in capsys.readouterr().out


def test_unchanged_content_is_not_rewritten(tmp_path: Path) -> None:
    output = tmp_path / "module.pyi"

    assert write_generated(output, "def run() -> None: ...\n") == Ok(WriteState.WRITTEN)
    modified = output.stat().st_mtime_ns
    assert write_generated(output, "def run() -> None: ...\n") == Ok(
        WriteState.UNCHANGED
    )
    assert output.stat().st_mtime_ns == modified


def test_source_outside_roots_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _ = _project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def outside() -> None: ...\n", encoding="utf-8")

    status = main(("--config", str(config), "generate", str(outside)))

    assert status == 1
    assert "outside configured source roots" in capsys.readouterr().err


def test_check_analyzes_in_memory_overlay_without_writing_stub(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, source = _project(tmp_path)

    status = main(("--config", str(config), "check", str(source)))

    assert status == 0, capsys.readouterr().err
    assert not (tmp_path / "generated").exists()


def test_check_reports_checker_diagnostics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, source = _project(tmp_path)
    source.write_text('value: int = "wrong"\n', encoding="utf-8")

    status = main(("--config", str(config), "check", str(source)))

    captured = capsys.readouterr()
    assert status == 1
    assert "Incompatible types in assignment" in captured.out
    assert "[assignment]" in captured.out


def test_check_runs_pyrefly_over_the_virtual_document(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, source = _project(tmp_path)
    pyrefly = Path(sys.executable).with_name("pyrefly")
    with config.open("a", encoding="utf-8") as stream:
        stream.write(
            f'\n[tool.typeforge.analysis]\nchecker = "pyrefly"\n'
            f'command = ["{pyrefly}", "lsp"]\n'
        )

    status = main(("--config", str(config), "check", str(source)))

    assert status == 0, capsys.readouterr().err
    assert not (tmp_path / "generated").exists()


def test_lsp_defaults_to_pyrefly(tmp_path: Path) -> None:
    invocation = parse_invocation(("--config", str(tmp_path / "pyproject.toml"), "lsp"))

    assert invocation.command == LspCommand(AnalysisChecker.PYREFLY)


def test_checker_override_does_not_reuse_another_checkers_command() -> None:
    configured = AnalysisConfig(
        checker=AnalysisChecker.MYPY,
        command=("custom-mypy",),
    )

    mypy = checker_adapter(configured, None)
    pyrefly = checker_adapter(configured, AnalysisChecker.PYREFLY)

    assert isinstance(mypy, MypyAdapter)
    assert mypy.configuration.command == ("custom-mypy",)
    assert not mypy.capabilities.in_memory_documents
    assert isinstance(pyrefly, PyreflyAdapter)
    assert pyrefly.command == PYREFLY_COMMAND
