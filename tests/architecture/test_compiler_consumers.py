"""Target projections consume the compiler's public planning seam."""

import pytest
from archunitpython import assert_passes, project_files

from .definitions import TYPE_FORGE


@pytest.mark.parametrize("consumer", ["overlay", "diagnostics"])
@pytest.mark.parametrize(
    "internal_owner",
    ["source", "adaptation", "specialization", "record_materialization"],
)
def test_consumers_do_not_reconstruct_compilation(
    consumer: str, internal_owner: str
) -> None:
    rule = (
        project_files(TYPE_FORGE.path.parent.as_posix())
        .in_path(TYPE_FORGE.mod(consumer).pattern)
        .should_not()
        .depend_on_files()
        .in_path(TYPE_FORGE.mod(f"compiler.{internal_owner}").pattern)
        .because("compilation and authored descriptions belong to compiler.pipeline")
    )

    assert_passes(rule)


@pytest.mark.parametrize("consumer", ["overlay", "diagnostics"])
def test_consumers_use_the_public_pipeline_interface(consumer: str) -> None:
    rule = (
        project_files(TYPE_FORGE.path.parent.as_posix())
        .in_path(TYPE_FORGE.mod(consumer).pattern)
        .should_not()
        .depend_on_files()
        .in_path(TYPE_FORGE.mod("compiler.pipeline").implementation_pattern)
        .because("the compilation plan is shared through the public pipeline interface")
    )

    assert_passes(rule)


@pytest.mark.parametrize("target", ["overlay", "diagnostics", "analysis", "adapters"])
def test_verification_analysis_has_no_target_dependencies(target: str) -> None:
    rule = (
        project_files(TYPE_FORGE.path.parent.as_posix())
        .in_path(TYPE_FORGE.mod("compiler.verification").pattern)
        .should_not()
        .depend_on_files()
        .in_path(TYPE_FORGE.mod(target).pattern)
        .because(
            "compiler obligations describe source sites and types, not checker edits"
        )
    )

    assert_passes(rule)
