from pathlib import Path

from returns.result import Failure, Success

from typeforge.compiler.config import (
    AnalysisChecker,
    AnalysisConfig,
    ConfigError,
    ProjectConfig,
    load_project_config,
)


def test_missing_typeforge_table_uses_defaults(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "example"\n')
    assert load_project_config(pyproject) == Success(ProjectConfig())


def test_configuration_is_loaded_from_pyproject(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.typeforge]
source-roots = ["package", "shared"]
output-dir = "generated"
max-arity = 8

[tool.typeforge.analysis]
checker = "pyrefly"
command = ["uv", "run", "pyrefly", "lsp"]
""".strip()
    )
    assert load_project_config(pyproject) == Success(
        ProjectConfig(
            source_roots=(Path("package"), Path("shared")),
            output_directory=Path("generated"),
            maximum_arity=8,
            analysis=AnalysisConfig(
                AnalysisChecker.PYREFLY,
                ("uv", "run", "pyrefly", "lsp"),
            ),
        )
    )


def test_invalid_configuration_returns_a_typed_error(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.typeforge]\nmax-arity = 0\n")
    assert load_project_config(pyproject) == Failure(
        ConfigError(pyproject, "max-arity must be a positive integer")
    )


def test_invalid_analysis_checker_returns_a_typed_error(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.typeforge.analysis]\nchecker = "unknown"\n',
        encoding="utf-8",
    )
    assert load_project_config(pyproject) == Failure(
        ConfigError(pyproject, "analysis.checker must be mypy or pyrefly")
    )
