"""Shared result handling is independent of domain and target modules."""

from archunitpython import assert_passes, project_files

from .definitions import TYPE_FORGE


def test_error_handling_has_no_typeforge_dependencies() -> None:
    rule = (
        project_files(TYPE_FORGE.path.parent.as_posix())
        .in_path(TYPE_FORGE.file("utils.error_handling").pattern)
        .should_not()
        .depend_on_files()
        .in_path(TYPE_FORGE.pattern)
        .because("shared result handling accepts error types supplied by its callers")
    )

    assert_passes(rule)
