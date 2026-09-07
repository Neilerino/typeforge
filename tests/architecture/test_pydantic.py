"""Private replacement responsibilities; the public hook cuts over in slice 6."""

import pytest
from archunitpython import assert_passes, project_files, project_layers
from archunitpython.layers.fluentapi.layers import LayeredArchitecture

from .definitions import SEMANTICS, TYPE_FORGE


@pytest.fixture
def architecture() -> LayeredArchitecture:
    architecture = project_layers(TYPE_FORGE.path.parent.as_posix())
    for layer in (
        *TYPE_FORGE.mod("pydantic").layers,
        SEMANTICS.interface,
        TYPE_FORGE.file("utils.error_handling"),
        TYPE_FORGE.interface,
    ):
        architecture.layer(layer.name).defined_by(layer.pattern)

    return architecture


def test_replacement_dependencies_keep_policy_and_emission_separate(
    architecture: LayeredArchitecture,
) -> None:
    integration = TYPE_FORGE.mod("pydantic")

    def file(name: str) -> str:
        return integration.file(name).name

    shared = (SEMANTICS.interface.name, TYPE_FORGE.file("utils.error_handling").name)
    rule = (
        architecture.where_layer(file("_errors"))
        .may_only_depend_on_layers()
        .where_layer(file("_policy"))
        .may_only_depend_on_layers(file("_errors"), SEMANTICS.interface.name)
        .where_layer(file("_type_system"))
        .may_only_depend_on_layers(file("_records"), file("_policy"), *shared)
        .where_layer(file("_records"))
        .may_only_depend_on_layers(*shared)
        .where_layer(file("_frontend"))
        .may_only_depend_on_layers(
            file("_errors"),
            file("_policy"),
            file("_type_system"),
            integration.interface.name,
            TYPE_FORGE.interface.name,
            *shared,
        )
        .where_layer(file("_emission"))
        .may_only_depend_on_layers(file("_errors"), file("_type_system"), *shared)
        .where_layer(file("_compile"))
        .may_only_depend_on_layers(
            file("_frontend"),
            file("_policy"),
            file("_type_system"),
            file("_emission"),
            file("_errors"),
            file("_records"),
            TYPE_FORGE.interface.name,
            *shared,
        )
        .where_layer(file("_annotation"))
        .may_only_depend_on_layers(file("_compile"), file("_errors"))
    )

    assert_passes(rule)


def test_pydantic_and_compiler_implementations_do_not_depend_on_each_other() -> None:
    integration = TYPE_FORGE.mod("pydantic")
    compiler = TYPE_FORGE.mod("compiler")
    for source, forbidden in ((integration, compiler), (compiler, integration)):
        assert_passes(
            project_files(TYPE_FORGE.path.parent.as_posix())
            .in_path(source.pattern)
            .should_not()
            .depend_on_files()
            .in_path(forbidden.pattern)
        )


def test_pydantic_implementation_has_no_cycles() -> None:
    assert_passes(
        project_files(TYPE_FORGE.path.parent.as_posix())
        .in_path(TYPE_FORGE.mod("pydantic").pattern)
        .should()
        .have_no_cycles()
    )
