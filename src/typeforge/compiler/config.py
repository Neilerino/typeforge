from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tomllib import TOMLDecodeError, loads
from typing import cast

from typeforge._result import Err, Ok, Result


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
class ConfigError:
    path: Path
    message: str


def load_project_config(path: Path) -> Result[ProjectConfig, ConfigError]:
    document_result = read_toml(path)
    if isinstance(document_result, Err):
        return document_result
    tool = mapping_value(document_result.value.get("tool"))
    typeforge = mapping_value(tool.get("typeforge")) if tool is not None else None
    if typeforge is None:
        return Ok(ProjectConfig())
    return parse_project_config(path, typeforge)


def read_toml(path: Path) -> Result[Mapping[str, object], ConfigError]:
    try:
        document = loads(path.read_text())
    except OSError as error:
        return Err(ConfigError(path, str(error)))
    except TOMLDecodeError as error:
        return Err(ConfigError(path, str(error)))
    return Ok(cast(Mapping[str, object], document))


def parse_project_config(
    path: Path,
    values: Mapping[str, object],
) -> Result[ProjectConfig, ConfigError]:
    roots_result = source_roots_value(path, values.get("source-roots", ["src"]))
    if isinstance(roots_result, Err):
        return roots_result
    output_result = path_value(
        path,
        "output-dir",
        values.get("output-dir", ".typeforge/stubs"),
    )
    if isinstance(output_result, Err):
        return output_result
    arity_result = arity_value(path, values.get("max-arity", 5))
    if isinstance(arity_result, Err):
        return arity_result
    analysis_result = analysis_value(path, values.get("analysis"))
    if isinstance(analysis_result, Err):
        return analysis_result
    return Ok(
        ProjectConfig(
            source_roots=roots_result.value,
            output_directory=output_result.value,
            maximum_arity=arity_result.value,
            analysis=analysis_result.value,
        )
    )


def analysis_value(
    path: Path,
    value: object,
) -> Result[AnalysisConfig, ConfigError]:
    if value is None:
        return Ok(AnalysisConfig())
    values = mapping_value(value)
    if values is None:
        return Err(ConfigError(path, "analysis must be a table"))
    checker_value = values.get("checker", AnalysisChecker.MYPY.value)
    if not isinstance(checker_value, str):
        return Err(ConfigError(path, "analysis.checker must be mypy or pyrefly"))
    try:
        checker = AnalysisChecker(checker_value)
    except ValueError:
        return Err(ConfigError(path, "analysis.checker must be mypy or pyrefly"))
    command_value = values.get("command")
    if command_value is None:
        return Ok(AnalysisConfig(checker))
    if not isinstance(command_value, list) or not command_value:
        return Err(
            ConfigError(path, "analysis.command must be a non-empty string array")
        )
    command_items = cast(list[object], command_value)
    if not all(isinstance(item, str) and item for item in command_items):
        return Err(
            ConfigError(path, "analysis.command must be a non-empty string array")
        )
    return Ok(AnalysisConfig(checker, tuple(cast(list[str], command_items))))


def source_roots_value(
    path: Path,
    value: object,
) -> Result[tuple[Path, ...], ConfigError]:
    if not isinstance(value, list) or not value:
        return Err(ConfigError(path, "source-roots must be a non-empty string array"))
    roots: list[Path] = []
    for root in cast(list[object], value):
        if not isinstance(root, str) or not root:
            return Err(
                ConfigError(path, "source-roots must be a non-empty string array")
            )
        roots.append(Path(root))
    return Ok(tuple(roots))


def path_value(
    path: Path,
    name: str,
    value: object,
) -> Result[Path, ConfigError]:
    if not isinstance(value, str) or not value:
        return Err(ConfigError(path, f"{name} must be a non-empty string"))
    return Ok(Path(value))


def arity_value(path: Path, value: object) -> Result[int, ConfigError]:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return Err(ConfigError(path, "max-arity must be a positive integer"))
    return Ok(value)


def mapping_value(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(Mapping[str, object], value)
