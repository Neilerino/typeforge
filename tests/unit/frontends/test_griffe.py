from pathlib import Path

from griffe import Module, load


def test_griffe_extracts_the_public_api_without_inspection() -> None:
    fixtures = Path(__file__).parent / "fixtures"
    loaded = load(
        "sample_package",
        search_paths=[fixtures],
        allow_inspection=False,
        resolve_aliases=True,
        resolve_external=False,
    )
    assert isinstance(loaded, Module)
    assert set(loaded.members) >= {"Parser", "User", "combine", "parse"}
    assert loaded["combine"].lineno == 31
