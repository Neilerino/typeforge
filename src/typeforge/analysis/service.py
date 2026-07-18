from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from returns.result import Failure, Result, Success

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
    return Result.do(
        analyzed
        for source in read_source(path)
        for document in transform_source(source, path, maximum_arity).alt(
            transform_error
        )
        for analyzed in adapter.analyze(
            AnalysisRequest(
                document=document,
                project_root=project_root,
                config_file=config_file,
            )
        ).alt(lambda error: checker_error(path, error))
    )


def read_source(path: Path) -> Result[str, AnalysisError]:
    try:
        return Success(path.read_text(encoding="utf-8"))
    except OSError as error:
        return Failure(AnalysisError(AnalysisErrorCode.READ, path, str(error)))


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
