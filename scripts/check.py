from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from textwrap import indent
from typing import TextIO


@dataclass(frozen=True, slots=True)
class CheckDefinition:
    name: str
    command: tuple[str, ...]
    default_paths: tuple[str, ...]
    path_scope: str | None = None


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CheckResult:
    check: Check
    returncode: int
    output: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


CHECK_DEFINITIONS = (
    CheckDefinition("pytest", ("pytest",), ("tests",), "tests"),
    CheckDefinition("ruff check", ("ruff", "check"), (".",)),
    CheckDefinition("ruff format", ("ruff", "format", "--check"), (".",)),
    CheckDefinition(
        "flake8 block spacing",
        (
            "flake8",
            "--isolated",
            "--require-plugins",
            "flake8-bas",
            "--select",
            "BAS6,BAS7",
            "--ignore",
            "BAS601,BAS602,BAS603,BAS701,BAS702,BAS703",
            "--extend-exclude",
            ".venv,.typeforge",
        ),
        (".",),
    ),
    CheckDefinition("mypy", ("mypy",), ("src",), "src"),
    CheckDefinition("pyright", ("pyright",), ("src",), "src"),
)


def paths_in_scope(paths: Sequence[str], scope: str) -> tuple[str, ...]:
    scope_path = Path(scope).resolve()
    selected: list[str] = []

    for path in paths:
        requested_path = Path(path).resolve()
        if requested_path.is_relative_to(scope_path):
            selected.append(path)
        elif scope_path.is_relative_to(requested_path):
            selected.append(scope)

    return tuple(selected)


def build_checks(paths: Sequence[str]) -> tuple[Check, ...]:
    checks: list[Check] = []

    for definition in CHECK_DEFINITIONS:
        if not paths:
            selected_paths = definition.default_paths
        elif definition.path_scope is None:
            selected_paths = tuple(paths)
        else:
            selected_paths = paths_in_scope(paths, definition.path_scope)

        if selected_paths:
            checks.append(
                Check(definition.name, (*definition.command, *selected_paths))
            )

    return tuple(checks)


def run_check(check: Check) -> CheckResult:
    try:
        completed = subprocess.run(
            check.command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return CheckResult(check, 127, f"Unable to start check: {error}")

    return CheckResult(check, completed.returncode, completed.stdout)


def run_checks(
    checks: Sequence[Check],
    runner: Callable[[Check], CheckResult] = run_check,
) -> tuple[CheckResult, ...]:
    if not checks:
        return ()

    with ThreadPoolExecutor(max_workers=len(checks)) as executor:
        return tuple(executor.map(runner, checks))


def report_results(results: Sequence[CheckResult], stream: TextIO = sys.stdout) -> bool:
    all_passed = True

    for result in results:
        if result.passed:
            print(f"PASS {result.check.name}", file=stream)
            continue

        all_passed = False
        print(f"FAIL {result.check.name}", file=stream)
        print(f"  $ {shlex.join(result.check.command)}", file=stream)
        output = result.output.rstrip()
        print(indent(output, "  ") if output else "  (no output)", file=stream)

    return all_passed


def parse_paths(argv: Sequence[str] | None = None) -> tuple[str, ...]:
    parser = argparse.ArgumentParser(
        description="Run the Typeforge development checks concurrently.",
    )
    parser.add_argument("paths", nargs="*")
    arguments = parser.parse_args(argv)
    return tuple(arguments.paths)


def main(argv: Sequence[str] | None = None) -> int:
    checks = build_checks(parse_paths(argv))
    return 0 if report_results(run_checks(checks)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
