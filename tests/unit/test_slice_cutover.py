"""The public authoring cutover retains only the internal branch representation."""

import re
from pathlib import Path

import pytest
from returns.result import Failure

import typeforge
from typeforge import Map
from typeforge._markers import Case, Default
from typeforge.compiler.pipeline import compile_source
from typeforge.compiler.source import SourceSyntaxError, parse_source


def test_legacy_branch_markers_are_not_public() -> None:
    for name in ("Case", "Default"):
        assert name not in typeforge.__all__
        assert not hasattr(typeforge, name)


@pytest.mark.parametrize("branch", [Case[int, str], Default[str]])
def test_public_map_rejects_canonical_branch_objects(branch: object) -> None:
    with pytest.raises(TypeError, match="selector: output"):
        Map[int, branch]


def test_public_map_rejects_branch_aliases_without_evaluating_them() -> None:
    type Branch = Case[int, str]

    with pytest.raises(TypeError, match="selector: output"):
        Map[int, Branch]


@pytest.mark.parametrize(
    ("imports", "expression"),
    [
        ("from typeforge import Map, Case", "Map[int, Case[int, str]]"),
        ("import typeforge as tf", "tf.Map[int, tf.Default[str]]"),
        ("from typeforge import Map as Select", "Select[int, Branch]"),
        ("from typeforge import Map", "Map[int, int:str, bytes]"),
    ],
)
def test_source_rejects_non_slice_branches_with_authored_locations(
    imports: str, expression: str
) -> None:
    source = f"{imports}\ntype Selected = {expression}\n"
    result = parse_source(source, Path("authored.py"))
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, SourceSyntaxError)
    assert "selector: output" in error.message
    assert error.span.start.line == 2


README_EXAMPLES = tuple(
    example
    for example in re.findall(
        r"```python\n(.*?)\n```", Path("README.md").read_text(), re.DOTALL
    )
    if "Map[" in example and "from typeforge import" in example
)


@pytest.mark.parametrize("source", README_EXAMPLES)
def test_readme_map_examples_compile(source: str) -> None:
    compile_source(source, Path("example.py"), maximum_arity=2).unwrap()


@pytest.mark.parametrize(
    "source",
    [example for example in README_EXAMPLES if "from pydantic import" in example],
)
def test_readme_runtime_map_examples_execute(source: str) -> None:
    # Fixed repository documentation, executed only by the runtime regression.
    namespace: dict[str, object] = {"__name__": __name__}
    exec(source, namespace)
