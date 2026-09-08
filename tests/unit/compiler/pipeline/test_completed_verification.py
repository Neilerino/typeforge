from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
from returns.result import Failure

from typeforge.compiler.pipeline import (
    AdaptationError,
    LoweringError,
    SourceSyntaxError,
    compile_source,
)


@pytest.mark.parametrize(
    ("source", "error_type"),
    [
        pytest.param("def broken(", SourceSyntaxError, id="syntax"),
        pytest.param(
            "from typeforge import Map\ndef broken() -> Map[int]: ...",
            AdaptationError,
            id="adaptation",
        ),
        pytest.param(
            "from typeforge import Each\ndef broken[T](value: Each[T]) -> T: ...",
            LoweringError,
            id="specialization",
        ),
    ],
)
def test_compiler_failures_prevent_implementation_analysis(
    source: str, error_type: type[SourceSyntaxError | AdaptationError | LoweringError]
) -> None:
    with patch(
        "typeforge.compiler.pipeline._compilation.analyze_implementations",
        side_effect=AssertionError("analysis must not run after compilation fails"),
    ):
        result = compile_source(source, Path("broken.py"), maximum_arity=1)

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), error_type)


def test_unexpected_analysis_failure_does_not_become_a_partial_plan() -> None:
    with (
        patch(
            "typeforge.compiler.pipeline._compilation.analyze_implementations",
            side_effect=RuntimeError("unexpected analysis failure"),
        ),
        pytest.raises(RuntimeError, match="unexpected analysis failure"),
    ):
        compile_source("def ordinary(): ...", Path("ordinary.py"), maximum_arity=1)


def test_verification_is_complete_and_independent_of_the_arity_frontier() -> None:
    source = dedent("""        from typeforge import Collect, Each, Map
        def convert[T](value: T) -> Map[T, int : str]:
            return value
        def collect[T](*values: Each[T]) -> Collect[T]: ...
        """)
    narrow = compile_source(source, Path("frontier.py"), maximum_arity=0).unwrap()
    wide = compile_source(source, Path("frontier.py"), maximum_arity=3).unwrap()

    assert narrow.module != wide.module
    assert len(narrow.verification.obligations) == 1
    assert narrow.verification == wide.verification


@pytest.mark.parametrize(
    "body", ["...", "yield value"], ids=["declaration", "generator"]
)
def test_unsupported_body_produces_a_complete_empty_verification_plan(
    body: str,
) -> None:
    source = (
        "from typeforge import Map\n"
        "def convert[T](value: T) -> Map[T, int : str]:\n"
        f"    {body}\n"
    )

    plan = compile_source(source, Path("unsupported.py"), maximum_arity=1).unwrap()

    assert plan.verification.obligations == ()
