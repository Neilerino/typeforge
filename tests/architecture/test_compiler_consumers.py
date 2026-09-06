"""Target projections consume the compiler's public planning seam."""

import re

import pytest
from archunitpython import assert_passes, project_files

from .definitions import TYPE_FORGE


@pytest.mark.parametrize("consumer", ["overlay", "diagnostics"])
@pytest.mark.parametrize(
    "internal_owner",
    [
        "source",
        "adaptation",
        "semantic_adapter",
        "specialization",
        "record_materialization",
        "module_surface",
        "verification",
    ],
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
@pytest.mark.parametrize("owner", ["pipeline", "stub_ir", "emission"])
def test_consumers_use_public_compiler_interfaces(consumer: str, owner: str) -> None:
    rule = (
        project_files(TYPE_FORGE.path.parent.as_posix())
        .in_path(TYPE_FORGE.mod(consumer).pattern)
        .should_not()
        .depend_on_files()
        .in_path(TYPE_FORGE.mod(f"compiler.{owner}").implementation_pattern)
        .because("plans, typing IR and emission have public compiler interfaces")
    )

    assert_passes(rule)


@pytest.mark.parametrize(
    "target", ["overlay", "diagnostics", "analysis", "adapters", "proxy", "cli"]
)
def test_compiler_has_no_target_dependencies(target: str) -> None:
    rule = (
        project_files(TYPE_FORGE.path.parent.as_posix())
        .in_path(TYPE_FORGE.mod("compiler").pattern)
        .should_not()
        .depend_on_files()
        .in_path(
            (
                TYPE_FORGE.file(target) if target == "cli" else TYPE_FORGE.mod(target)
            ).pattern
        )
        .because(
            "compiler obligations describe source sites and types, not checker edits"
        )
    )

    assert_passes(rule)


@pytest.mark.parametrize("consumer", ["overlay", "diagnostics"])
def test_consumers_do_not_parse_or_inspect_python_syntax(consumer: str) -> None:
    rule = (
        project_files(TYPE_FORGE.path.parent.as_posix())
        .in_path(TYPE_FORGE.mod(consumer).pattern)
        .should_not()
        .depend_on_external_modules()
        .matching(re.compile(r"^ast(?:\.|$)"))
        .because(
            "source interpretation belongs to the compiler; consumers use its facts"
        )
    )

    assert_passes(rule)
