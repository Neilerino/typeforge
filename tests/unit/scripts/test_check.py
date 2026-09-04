from io import StringIO
from threading import Barrier

from scripts.check import (
    Check,
    CheckResult,
    build_checks,
    report_results,
    run_checks,
)


def test_checks_use_their_default_paths() -> None:
    assert build_checks(()) == (
        Check("pytest", ("pytest", "tests")),
        Check("ruff check", ("ruff", "check", ".")),
        Check("ruff format", ("ruff", "format", "--check", ".")),
        Check(
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
                ".",
            ),
        ),
        Check("mypy", ("mypy", "src")),
        Check("pyright", ("pyright", "src")),
    )


def test_paths_are_routed_to_applicable_checks() -> None:
    source = "src/typeforge/compiler/_semantic_lowering.py"
    test = "tests/unit/compiler/test_semantic_lowering.py"

    assert build_checks((source, test)) == (
        Check("pytest", ("pytest", test)),
        Check("ruff check", ("ruff", "check", source, test)),
        Check("ruff format", ("ruff", "format", "--check", source, test)),
        Check(
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
                source,
                test,
            ),
        ),
        Check("mypy", ("mypy", source)),
        Check("pyright", ("pyright", source)),
    )


def test_parent_path_uses_the_relevant_default_scope() -> None:
    assert build_checks((".",)) == (
        Check("pytest", ("pytest", "tests")),
        Check("ruff check", ("ruff", "check", ".")),
        Check("ruff format", ("ruff", "format", "--check", ".")),
        Check(
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
                ".",
            ),
        ),
        Check("mypy", ("mypy", "src")),
        Check("pyright", ("pyright", "src")),
    )


def test_checks_run_concurrently_and_results_keep_their_declared_order() -> None:
    checks = (
        Check("first", ("first",)),
        Check("second", ("second",)),
    )
    both_started = Barrier(len(checks))

    def wait_for_other_check(check: Check) -> CheckResult:
        both_started.wait(timeout=5)
        return CheckResult(check, 0, "hidden output")

    results = run_checks(checks, wait_for_other_check)

    assert tuple(result.check.name for result in results) == ("first", "second")


def test_successful_check_output_is_suppressed() -> None:
    stream = StringIO()
    result = CheckResult(Check("pytest", ("pytest", "tests")), 0, "12 passed\n")

    all_passed = report_results((result,), stream)

    assert all_passed
    assert stream.getvalue() == "PASS pytest\n"


def test_failed_check_output_and_command_are_reported() -> None:
    stream = StringIO()
    result = CheckResult(
        Check("mypy", ("mypy", "src")),
        1,
        "src/typeforge/example.py:1: error: Example failure\n",
    )

    all_passed = report_results((result,), stream)

    assert not all_passed
    assert stream.getvalue() == (
        "FAIL mypy\n"
        "  $ mypy src\n"
        "  src/typeforge/example.py:1: error: Example failure\n"
    )


def test_failed_check_without_output_is_reported() -> None:
    stream = StringIO()
    result = CheckResult(Check("pyright", ("pyright", "src")), 1, "")

    report_results((result,), stream)

    assert stream.getvalue() == "FAIL pyright\n  $ pyright src\n  (no output)\n"
