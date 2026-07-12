import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from typeforge._result import Err, Ok, Result
from typeforge.adapters.mypy import MypyAdapter, MypyConfiguration
from typeforge.adapters.pyrefly import PYREFLY_COMMAND, PyreflyAdapter
from typeforge.analysis.model import CheckerAdapter, DiagnosticSeverity
from typeforge.analysis.service import analyze_path
from typeforge.compiler.config import (
    AnalysisChecker,
    AnalysisConfig,
    ProjectConfig,
    load_project_config,
)
from typeforge.compiler.pipeline import GeneratedModule, generate_module
from typeforge.proxy import ProxyStreams, pyrefly_proxy_configuration, run_proxy


@dataclass(frozen=True, slots=True)
class GenerateCommand:
    paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class ShowCommand:
    path: Path


@dataclass(frozen=True, slots=True)
class CheckCommand:
    paths: tuple[Path, ...]
    checker: AnalysisChecker | None


@dataclass(frozen=True, slots=True)
class LspCommand:
    checker: AnalysisChecker


type Command = GenerateCommand | ShowCommand | CheckCommand | LspCommand


@dataclass(frozen=True, slots=True)
class Invocation:
    config_path: Path
    command: Command


@dataclass(frozen=True, slots=True)
class Project:
    root: Path
    source_roots: tuple[Path, ...]
    output_directory: Path
    maximum_arity: int
    analysis: AnalysisConfig


class CliErrorCode(StrEnum):
    CONFIG = "config"
    SOURCE = "source"
    GENERATION = "generation"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class CliError:
    code: CliErrorCode
    message: str
    path: Path | None = None


class WriteState(StrEnum):
    WRITTEN = "written"
    UNCHANGED = "unchanged"


def main(argv: Sequence[str] | None = None) -> int:
    invocation = parse_invocation(argv)
    project_result = load_project(invocation.config_path)
    if isinstance(project_result, Err):
        _print_error(project_result.error)
        return 1
    project = project_result.value

    if isinstance(invocation.command, ShowCommand):
        generated = _generate(project, invocation.command.path)
        if isinstance(generated, Err):
            _print_error(generated.error)
            return 1
        sys.stdout.write(generated.value.content)
        return 0

    if isinstance(invocation.command, CheckCommand):
        return _check(project, invocation.config_path, invocation.command)

    if isinstance(invocation.command, LspCommand):
        return _lsp(project, invocation.command)

    sources_result = resolve_sources(project, invocation.command.paths)
    if isinstance(sources_result, Err):
        _print_error(sources_result.error)
        return 1
    for source in sources_result.value:
        generated = _generate(project, source)
        if isinstance(generated, Err):
            _print_error(generated.error)
            return 1
        output_result = output_path(project, source)
        if isinstance(output_result, Err):
            _print_error(output_result.error)
            return 1
        written = write_generated(output_result.value, generated.value.content)
        if isinstance(written, Err):
            _print_error(written.error)
            return 1
    return 0


def parse_invocation(argv: Sequence[str] | None = None) -> Invocation:
    parser = argparse.ArgumentParser(prog="typeforge")
    parser.add_argument("--config", type=Path, default=Path("pyproject.toml"))
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("paths", nargs="*", type=Path)
    show = commands.add_parser("show")
    show.add_argument("path", type=Path)
    check = commands.add_parser("check")
    check.add_argument("paths", nargs="*", type=Path)
    check.add_argument("--checker", choices=tuple(AnalysisChecker))
    lsp = commands.add_parser("lsp")
    lsp.add_argument(
        "--checker",
        choices=(AnalysisChecker.PYREFLY.value,),
        default=AnalysisChecker.PYREFLY.value,
    )
    parsed = parser.parse_args(argv)
    config_path = _absolute(parsed.config)
    if parsed.command == "show":
        return Invocation(config_path, ShowCommand(_absolute(parsed.path)))
    if parsed.command == "check":
        checker = (
            AnalysisChecker(parsed.checker) if parsed.checker is not None else None
        )
        return Invocation(
            config_path,
            CheckCommand(tuple(_absolute(path) for path in parsed.paths), checker),
        )
    if parsed.command == "lsp":
        return Invocation(config_path, LspCommand(AnalysisChecker(parsed.checker)))
    return Invocation(
        config_path,
        GenerateCommand(tuple(_absolute(path) for path in parsed.paths)),
    )


def load_project(config_path: Path) -> Result[Project, CliError]:
    loaded = load_project_config(config_path)
    if isinstance(loaded, Err):
        return Err(
            CliError(CliErrorCode.CONFIG, loaded.error.message, loaded.error.path)
        )
    return Ok(_resolve_project(config_path.parent, loaded.value))


def resolve_sources(
    project: Project, requested: tuple[Path, ...]
) -> Result[tuple[Path, ...], CliError]:
    if not requested:
        return Ok(discover_sources(project))
    sources: set[Path] = set()
    for requested_path in requested:
        path = _absolute_from(project.root, requested_path)
        if path.is_dir():
            sources.update(_discover_root(path, project.output_directory))
        elif path.is_file() and path.suffix == ".py":
            sources.add(path)
        else:
            return Err(
                CliError(
                    CliErrorCode.SOURCE,
                    "source must be a Python file or directory",
                    path,
                )
            )
    for source in sources:
        if _containing_root(project, source) is None:
            return Err(
                CliError(
                    CliErrorCode.SOURCE,
                    "source is outside configured source roots",
                    source,
                )
            )
    return Ok(tuple(sorted(sources)))


def discover_sources(project: Project) -> tuple[Path, ...]:
    sources = {
        source
        for root in project.source_roots
        for source in _discover_root(root, project.output_directory)
    }
    return tuple(sorted(sources))


def output_path(project: Project, source: Path) -> Result[Path, CliError]:
    root = _containing_root(project, source)
    if root is None:
        return Err(
            CliError(
                CliErrorCode.SOURCE,
                "source is outside configured source roots",
                source,
            )
        )
    relative = source.relative_to(root).with_suffix(".pyi")
    return Ok(project.output_directory / relative)


def write_generated(path: Path, content: str) -> Result[WriteState, CliError]:
    try:
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return Ok(WriteState.UNCHANGED)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=".typeforge-"
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
    except OSError as error:
        return Err(CliError(CliErrorCode.WRITE, str(error), path))
    return Ok(WriteState.WRITTEN)


def _generate(project: Project, path: Path) -> Result[GeneratedModule, CliError]:
    source = _absolute_from(project.root, path)
    generated = generate_module(source, project.maximum_arity)
    if isinstance(generated, Err):
        return Err(CliError(CliErrorCode.GENERATION, generated.error.message, source))
    return Ok(generated.value)


def _resolve_project(root: Path, config: ProjectConfig) -> Project:
    resolved_root = root.resolve()
    return Project(
        resolved_root,
        tuple(_absolute_from(resolved_root, path) for path in config.source_roots),
        _absolute_from(resolved_root, config.output_directory),
        config.maximum_arity,
        config.analysis,
    )


def _check(project: Project, config_path: Path, command: CheckCommand) -> int:
    sources = resolve_sources(project, command.paths)
    if isinstance(sources, Err):
        _print_error(sources.error)
        return 1
    adapter = checker_adapter(project.analysis, command.checker)
    has_errors = False
    for source in sources.value:
        analyzed = analyze_path(
            source,
            project.root,
            project.maximum_arity,
            adapter,
            config_path,
        )
        if isinstance(analyzed, Err):
            _print_error(
                CliError(
                    CliErrorCode.GENERATION,
                    analyzed.error.message,
                    analyzed.error.path,
                )
            )
            if analyzed.error.detail:
                print(analyzed.error.detail, file=sys.stderr)
            return 1
        for diagnostic in analyzed.value.diagnostics:
            position = diagnostic.span.start
            code = f" [{diagnostic.code}]" if diagnostic.code else ""
            print(
                f"{diagnostic.path}:{position.line + 1}:{position.column + 1}: "
                f"{diagnostic.severity.value}: {diagnostic.message}{code}"
            )
            has_errors = has_errors or (diagnostic.severity is DiagnosticSeverity.ERROR)
    return 1 if has_errors else 0


def checker_adapter(
    configured: AnalysisConfig,
    override: AnalysisChecker | None,
) -> CheckerAdapter:
    checker = override or configured.checker
    command = configured.command if override in (None, configured.checker) else None
    if checker is AnalysisChecker.PYREFLY:
        return PyreflyAdapter(command=command or PYREFLY_COMMAND)
    return MypyAdapter(
        configuration=MypyConfiguration(
            command=command or (sys.executable, "-m", "mypy")
        )
    )


def _lsp(project: Project, command: LspCommand) -> int:
    if command.checker is not AnalysisChecker.PYREFLY:
        print("typeforge: checker does not provide an LSP adapter", file=sys.stderr)
        return 1
    backend_command = (
        project.analysis.command
        if project.analysis.checker is AnalysisChecker.PYREFLY
        and project.analysis.command is not None
        else PYREFLY_COMMAND
    )
    result = run_proxy(
        ProxyStreams(sys.stdin.buffer, sys.stdout.buffer),
        pyrefly_proxy_configuration(
            project_root=project.root,
            backend_command=backend_command,
            maximum_arity=project.maximum_arity,
        ),
    )
    if isinstance(result, Err):
        print(
            f"typeforge: {result.error.code.value}: {result.error.message}",
            file=sys.stderr,
        )
        return 1
    return 0


def _discover_root(root: Path, output_directory: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    sources: list[Path] = []
    for source in root.rglob("*.py"):
        relative = source.relative_to(root)
        if _is_private(relative) or source.is_relative_to(output_directory):
            continue
        sources.append(source.resolve())
    return tuple(sorted(sources))


def _is_private(path: Path) -> bool:
    return any(part.startswith((".", "_")) for part in path.parts[:-1])


def _containing_root(project: Project, source: Path) -> Path | None:
    absolute = source.resolve()
    return next(
        (root for root in project.source_roots if absolute.is_relative_to(root)),
        None,
    )


def _absolute_from(root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _absolute(path: Path) -> Path:
    return path.resolve()


def _print_error(error: CliError) -> None:
    location = f"{error.path}: " if error.path is not None else ""
    print(f"typeforge: {location}{error.message}", file=sys.stderr)
