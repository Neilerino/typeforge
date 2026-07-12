from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from typeforge._result import Err, Ok, Result
from typeforge.analysis.model import (
    AnalysisRequest,
    AnalysisResult,
    CheckerAdapter,
    CheckerError,
)
from typeforge.overlay import OverlayError, transform_source


class AnalysisErrorCode(StrEnum):
    READ = "read"
    TRANSFORM = "transform"
    CHECKER = "checker"


@dataclass(frozen=True, slots=True)
class AnalysisError:
    code: AnalysisErrorCode
    path: Path
    message: str
    detail: str | None = None


def analyze_path(
    path: Path,
    project_root: Path,
    maximum_arity: int,
    adapter: CheckerAdapter,
    config_file: Path | None = None,
) -> Result[AnalysisResult, AnalysisError]:
    source = read_source(path)
    if isinstance(source, Err):
        return source
    transformed = transform_source(source.value, path, maximum_arity)
    if isinstance(transformed, Err):
        return Err(transform_error(transformed.error))
    analyzed = adapter.analyze(
        AnalysisRequest(
            document=transformed.value,
            project_root=project_root,
            config_file=config_file,
        )
    )
    if isinstance(analyzed, Err):
        return Err(checker_error(path, analyzed.error))
    return Ok(analyzed.value)


def read_source(path: Path) -> Result[str, AnalysisError]:
    try:
        return Ok(path.read_text(encoding="utf-8"))
    except OSError as error:
        return Err(AnalysisError(AnalysisErrorCode.READ, path, str(error)))


def transform_error(error: OverlayError) -> AnalysisError:
    return AnalysisError(
        AnalysisErrorCode.TRANSFORM,
        error.path,
        error.message,
        error.code.value,
    )


def checker_error(path: Path, error: CheckerError) -> AnalysisError:
    return AnalysisError(
        AnalysisErrorCode.CHECKER,
        path,
        error.message,
        error.detail,
    )
