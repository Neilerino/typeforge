import json
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from typing import Protocol, cast

from typeforge._result import Err, Ok, Result
from typeforge.analysis.mapping import generated_span_to_authored
from typeforge.analysis.model import (
    AnalysisRequest,
    AnalysisResult,
    CheckerCapabilities,
    CheckerError,
    Diagnostic,
    DiagnosticSeverity,
    SourcePosition,
    SourceSpan,
    VirtualDocument,
)
from typeforge.analysis.positions import source_position_from_utf8


@dataclass(frozen=True, slots=True)
class MypyConfiguration:
    command: tuple[str, ...] = (sys.executable, "-m", "mypy")


@dataclass(frozen=True, slots=True)
class MypyRunRequest:
    command: tuple[str, ...]
    project_root: Path
    source_path: Path
    generated_text: str
    config_file: Path | None
    extra_arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MypyRunOutput:
    return_code: int
    stdout: str
    stderr: str


class MypyRunner(Protocol):
    def __call__(
        self, request: MypyRunRequest
    ) -> Result[MypyRunOutput, CheckerError]: ...


MYPY_CAPABILITIES = CheckerCapabilities(
    diagnostics=True,
    hover=False,
    completion=False,
    signature_help=False,
    definitions=False,
    references=False,
    rename=False,
    code_actions=False,
    in_memory_documents=True,
)

_MYPY_BUILD_LOCK = threading.Lock()


def run_mypy_in_memory(
    request: MypyRunRequest,
) -> Result[MypyRunOutput, CheckerError]:
    try:
        from mypy.build import BuildSource, build
        from mypy.errors import CompileError
        from mypy.main import process_options
    except ImportError as error:
        return Err(
            CheckerError(
                checker="mypy",
                message="unable to import mypy",
                detail=str(error),
            )
        )
    stdout = StringIO()
    stderr = StringIO()
    try:
        with mypy_project_context(request.project_root):
            sources, options = process_options(
                list(mypy_option_arguments(request)),
                stdout=stdout,
                stderr=stderr,
            )
            source = next(
                (
                    item
                    for item in sources
                    if item.path is not None
                    and Path(item.path).resolve() == request.source_path.resolve()
                ),
                None,
            )
            if source is None:
                return Err(
                    CheckerError(
                        checker="mypy",
                        message="mypy did not resolve the requested source",
                        detail=str(request.source_path),
                    )
                )
            options.incremental = False
            options.cache_dir = os.devnull
            result = build(
                [
                    BuildSource(
                        source.path,
                        source.module,
                        request.generated_text,
                        source.base_dir,
                        source.followed,
                    )
                ],
                options,
                stdout=stdout,
                stderr=stderr,
            )
    except (CompileError, OSError, SystemExit) as exception:
        return Err(
            CheckerError(
                checker="mypy",
                message="mypy analysis failed",
                detail=stderr.getvalue() or stdout.getvalue() or str(exception),
            )
        )
    diagnostics: list[str] = []
    has_errors = False
    for path, errors in result.manager.errors.error_info_map.items():
        for info in errors:
            if info.hidden:
                continue
            has_errors = has_errors or info.severity == "error"
            diagnostics.append(
                json.dumps(
                    {
                        "file": path,
                        "line": info.line,
                        "column": info.column,
                        "end_line": info.end_line,
                        "end_column": info.end_column,
                        "message": info.message,
                        "code": info.code.code if info.code is not None else None,
                        "severity": info.severity,
                    }
                )
            )
    output = "\n".join(diagnostics)
    return Ok(
        MypyRunOutput(
            return_code=1 if has_errors else 0,
            stdout=f"{output}\n" if output else "",
            stderr=stderr.getvalue(),
        )
    )


@contextmanager
def mypy_project_context(project_root: Path) -> Generator[None]:
    with _MYPY_BUILD_LOCK:
        previous = Path.cwd()
        os.chdir(project_root)
        try:
            yield
        finally:
            os.chdir(previous)


def mypy_option_arguments(request: MypyRunRequest) -> tuple[str, ...]:
    config_arguments: tuple[str, ...] = ()
    if request.config_file is not None:
        config_arguments = ("--config-file", str(request.config_file))
    command_arguments = (
        request.command[3:]
        if request.command[1:3] == ("-m", "mypy")
        else request.command[1:]
    )
    return (
        *command_arguments,
        *config_arguments,
        *request.extra_arguments,
        str(request.source_path),
    )


def run_mypy_shadow_file(
    request: MypyRunRequest,
) -> Result[MypyRunOutput, CheckerError]:
    try:
        with tempfile.TemporaryDirectory(prefix="typeforge-mypy-") as temporary:
            temporary_path = Path(temporary)
            shadow_path = temporary_path / request.source_path.name
            shadow_path.write_text(request.generated_text, encoding="utf-8")
            arguments = build_mypy_arguments(
                request,
                shadow_path,
                temporary_path / "cache",
            )
            completed = subprocess.run(
                arguments,
                cwd=request.project_root,
                check=False,
                capture_output=True,
                text=True,
            )
    except OSError as error:
        return Err(
            CheckerError(
                checker="mypy",
                message="unable to run mypy",
                detail=str(error),
            )
        )
    return Ok(
        MypyRunOutput(
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    )


@dataclass(frozen=True, slots=True)
class MypyAdapter:
    configuration: MypyConfiguration = MypyConfiguration()
    runner: MypyRunner = run_mypy_in_memory

    @property
    def name(self) -> str:
        return "mypy"

    @property
    def capabilities(self) -> CheckerCapabilities:
        if self.runner is run_mypy_in_memory and not uses_current_mypy(
            self.configuration.command
        ):
            return replace(MYPY_CAPABILITIES, in_memory_documents=False)
        return MYPY_CAPABILITIES

    def analyze(self, request: AnalysisRequest) -> Result[AnalysisResult, CheckerError]:
        if request.hover_queries:
            return Err(
                CheckerError(
                    checker=self.name,
                    message="mypy does not support hover queries",
                )
            )
        runner = self.runner
        if runner is run_mypy_in_memory and not uses_current_mypy(
            self.configuration.command
        ):
            runner = run_mypy_shadow_file
        run_result = runner(
            MypyRunRequest(
                command=self.configuration.command,
                project_root=request.project_root,
                source_path=request.document.path,
                generated_text=request.document.generated_text,
                config_file=request.config_file,
                extra_arguments=request.extra_arguments,
            )
        )
        if isinstance(run_result, Err):
            return run_result
        if run_result.value.return_code not in (0, 1):
            return Err(
                CheckerError(
                    checker=self.name,
                    message="mypy analysis failed",
                    detail=run_result.value.stderr or run_result.value.stdout,
                )
            )
        diagnostics = parse_mypy_diagnostics(
            run_result.value.stdout,
            request.document,
            request.project_root,
        )
        if isinstance(diagnostics, Err):
            return diagnostics
        return Ok(AnalysisResult(diagnostics=diagnostics.value))


def uses_current_mypy(command: tuple[str, ...]) -> bool:
    return command[:3] == (sys.executable, "-m", "mypy")


def build_mypy_arguments(
    request: MypyRunRequest,
    shadow_path: Path,
    cache_path: Path,
) -> tuple[str, ...]:
    config_arguments: tuple[str, ...] = ()
    if request.config_file is not None:
        config_arguments = ("--config-file", str(request.config_file))
    return (
        *request.command,
        "--output",
        "json",
        "--no-error-summary",
        "--show-error-end",
        "--cache-dir",
        str(cache_path),
        *config_arguments,
        *request.extra_arguments,
        "--shadow-file",
        str(request.source_path),
        str(shadow_path),
        str(request.source_path),
    )


def parse_mypy_diagnostics(
    output: str,
    document: VirtualDocument,
    project_root: Path,
) -> Result[tuple[Diagnostic, ...], CheckerError]:
    diagnostics: list[Diagnostic] = []
    for line in output.splitlines():
        if not line:
            continue
        parsed = parse_mypy_diagnostic(line, document, project_root)
        if isinstance(parsed, Err):
            return parsed
        diagnostics.append(parsed.value)
    return Ok(tuple(diagnostics))


def parse_mypy_diagnostic(
    line: str,
    document: VirtualDocument,
    project_root: Path,
) -> Result[Diagnostic, CheckerError]:
    try:
        value: object = json.loads(line)
    except json.JSONDecodeError as error:
        return invalid_mypy_output(line, str(error))
    if not isinstance(value, Mapping):
        return invalid_mypy_output(line, "diagnostic is not an object")
    diagnostic = cast(Mapping[str, object], value)

    file = diagnostic.get("file")
    line_number = diagnostic.get("line")
    column = diagnostic.get("column")
    end_line = diagnostic.get("end_line")
    end_column = diagnostic.get("end_column")
    message = diagnostic.get("message")
    code = diagnostic.get("code")
    severity = diagnostic.get("severity")
    if not (
        isinstance(file, str)
        and isinstance(line_number, int)
        and isinstance(column, int)
        and isinstance(end_line, int)
        and isinstance(end_column, int)
        and isinstance(message, str)
        and (code is None or isinstance(code, str))
        and isinstance(severity, str)
    ):
        return invalid_mypy_output(line, "diagnostic has invalid fields")

    path = Path(file)
    if not path.is_absolute():
        path = project_root / path
    document_path = document.path
    if not document_path.is_absolute():
        document_path = project_root / document_path
    start = source_position(document.generated_text, line_number - 1, column)
    end = source_position(document.generated_text, end_line - 1, end_column)
    generated_span = SourceSpan(start=start, end=end)
    span = (
        generated_span_to_authored(document, generated_span)
        if path.resolve() == document_path.resolve()
        else generated_span
    )
    return Ok(
        Diagnostic(
            checker="mypy",
            path=path.resolve(),
            span=span,
            severity=mypy_severity(severity),
            message=message,
            code=code,
        )
    )


def source_position(text: str, line: int, column: int) -> SourcePosition:
    return source_position_from_utf8(text, line, column)


def mypy_severity(severity: str) -> DiagnosticSeverity:
    if severity == "warning":
        return DiagnosticSeverity.WARNING
    if severity == "note":
        return DiagnosticSeverity.INFORMATION
    return DiagnosticSeverity.ERROR


def invalid_mypy_output(line: str, reason: str) -> Err[CheckerError]:
    return Err(
        CheckerError(
            checker="mypy",
            message="unable to parse mypy output",
            detail=f"{reason}: {line}",
        )
    )
