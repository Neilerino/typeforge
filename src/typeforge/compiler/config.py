from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tomllib import TOMLDecodeError, loads
from typing import cast

from returns.result import Result, Success, safe


class AnalysisChecker(StrEnum):
    MYPY = "mypy"
    PYREFLY = "pyrefly"


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    checker: AnalysisChecker = AnalysisChecker.MYPY
    command: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    source_roots: tuple[Path, ...] = (Path("src"),)
    output_directory: Path = Path(".typeforge/stubs")
    maximum_arity: int = 5
    analysis: AnalysisConfig = AnalysisConfig()


@dataclass(frozen=True, slots=True)
class ConfigError(Exception):
    path: Path
    message: str


def load_project_config(path: Path) -> Result[ProjectConfig, ConfigError]:
    return Result.do(
        config
        for document in read_toml(path)
        for config in _load_config_document(path, document)
    )


def _load_config_document(
    path: Path, document: Mapping[str, object]
) -> Result[ProjectConfig, ConfigError]:
    tool = mapping_value(document.get("tool"))
    typeforge = mapping_value(tool.get("typeforge")) if tool is not None else None
    return (
        Success(ProjectConfig())
        if typeforge is None
        else parse_project_config(path, typeforge)
    )


def read_toml(path: Path) -> Result[Mapping[str, object], ConfigError]:
    return _read_toml(path).alt(lambda error: ConfigError(path, str(error)))


@safe(exceptions=(OSError, TOMLDecodeError))
def _read_toml(path: Path) -> Mapping[str, object]:
    return cast(Mapping[str, object], loads(path.read_text()))


def parse_project_config(
    path: Path,
    values: Mapping[str, object],
) -> Result[ProjectConfig, ConfigError]:
    return Result.do(
        ProjectConfig(
            source_roots=roots,
            output_directory=output,
            maximum_arity=arity,
            analysis=analysis,
        )
        for roots in source_roots_value(path, values.get("source-roots", ["src"]))
        for output in path_value(
            path, "output-dir", values.get("output-dir", ".typeforge/stubs")
        )
        for arity in arity_value(path, values.get("max-arity", 5))
        for analysis in analysis_value(path, values.get("analysis"))
    )


@safe(exceptions=(ConfigError,))
def analysis_value(path: Path, value: object) -> AnalysisConfig:
    if value is None:
        return AnalysisConfig()
    values = mapping_value(value)
    if values is None:
        raise ConfigError(path, "analysis must be a table")
    checker_value = values.get("checker", AnalysisChecker.MYPY.value)
    if not isinstance(checker_value, str):
        raise ConfigError(path, "analysis.checker must be mypy or pyrefly")
    try:
        checker = AnalysisChecker(checker_value)
    except ValueError:
        raise ConfigError(path, "analysis.checker must be mypy or pyrefly") from None
    command_value = values.get("command")
    if command_value is None:
        return AnalysisConfig(checker)
    if not isinstance(command_value, list) or not command_value:
        raise ConfigError(path, "analysis.command must be a non-empty string array")
    command_items = cast(list[object], command_value)
    if not all(isinstance(item, str) and item for item in command_items):
        raise ConfigError(path, "analysis.command must be a non-empty string array")
    return AnalysisConfig(checker, tuple(cast(list[str], command_items)))


@safe(exceptions=(ConfigError,))
def source_roots_value(path: Path, value: object) -> tuple[Path, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError(path, "source-roots must be a non-empty string array")
    roots: list[Path] = []
    for root in cast(list[object], value):
        if not isinstance(root, str) or not root:
            raise ConfigError(path, "source-roots must be a non-empty string array")
        roots.append(Path(root))
    return tuple(roots)


@safe(exceptions=(ConfigError,))
def path_value(path: Path, name: str, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(path, f"{name} must be a non-empty string")
    return Path(value)


@safe(exceptions=(ConfigError,))
def arity_value(path: Path, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(path, "max-arity must be a positive integer")
    return value


def mapping_value(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(Mapping[str, object], value)
