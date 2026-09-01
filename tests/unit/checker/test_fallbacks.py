from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess, run
from sys import executable

import pytest


@dataclass(frozen=True, slots=True)
class CheckerCommand:
    name: str
    arguments: tuple[str, ...]
    fixture_name: str


CHECKERS = (
    CheckerCommand(
        "mypy",
        (executable, "-m", "mypy"),
        "variadic_fallback_mypy.py",
    ),
    CheckerCommand(
        "pyright",
        (executable, "-m", "pyright"),
        "variadic_fallback_pyright.py",
    ),
)

CONDITIONAL_MAP_CHECKERS = (
    CheckerCommand(
        "mypy",
        (executable, "-m", "mypy"),
        "conditional_map_fallback_mypy.py",
    ),
    CheckerCommand(
        "pyright",
        (executable, "-m", "pyright"),
        "conditional_map_fallback_pyright.py",
    ),
)

ECS_QUERY_CHECKERS = (
    CheckerCommand(
        "mypy",
        (executable, "-m", "mypy"),
        "ecs_query_mypy.py",
    ),
    CheckerCommand(
        "pyright",
        (executable, "-m", "pyright"),
        "ecs_query_pyright.py",
    ),
)


@pytest.mark.parametrize("checker", CHECKERS, ids=lambda checker: checker.name)
def test_variadic_fallback(checker: CheckerCommand) -> None:
    fixture = Path(__file__).parent / "fixtures" / checker.fixture_name
    completed = run(
        (*checker.arguments, str(fixture)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert_checker_succeeded(completed)


@pytest.mark.parametrize(
    "checker",
    CONDITIONAL_MAP_CHECKERS,
    ids=lambda checker: checker.name,
)
def test_conditional_map_fallback(checker: CheckerCommand) -> None:
    fixture = Path(__file__).parent / "fixtures" / checker.fixture_name
    completed = run(
        (*checker.arguments, str(fixture)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert_checker_succeeded(completed)


@pytest.mark.parametrize(
    "checker",
    ECS_QUERY_CHECKERS,
    ids=lambda checker: checker.name,
)
def test_ecs_query_relationship(checker: CheckerCommand) -> None:
    fixture = Path(__file__).parent / "fixtures" / checker.fixture_name
    completed = run(
        (*checker.arguments, str(fixture)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert_checker_succeeded(completed)


def assert_checker_succeeded(completed: CompletedProcess[str]) -> None:
    assert completed.returncode == 0, completed.stdout + completed.stderr
