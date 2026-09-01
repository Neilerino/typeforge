from pathlib import Path

import pytest
from stubpy import ExecutionMode, StubConfig, StubContext, generate_stub


def generate_sample_stub(tmp_path: Path) -> str:
    fixture = Path(__file__).parent / "fixtures" / "sample_package" / "__init__.py"
    output = tmp_path / "sample_module.pyi"
    context = StubContext(config=StubConfig(execution_mode=ExecutionMode.AST_ONLY))
    return generate_stub(str(fixture), str(output), context)


def test_stubpy_generates_a_public_skeleton_without_execution(tmp_path: Path) -> None:
    content = generate_sample_stub(tmp_path)
    assert "class User(TypedDict):" in content
    assert "class Parser:" in content
    assert "def combine() -> Parser[Collect[T]]:" in content
    assert "def _private_function" not in content


@pytest.mark.xfail(
    strict=True,
    reason="stubpy 0.4.0 AST_ONLY drops PEP 695 and function parameters",
)
def test_stubpy_preserves_modern_generic_signatures(tmp_path: Path) -> None:
    content = generate_sample_stub(tmp_path)
    assert "class Parser[T]:" in content
    assert "def combine[T](*parsers: Each[Parser[T]]) -> Parser[Collect[T]]:" in content
