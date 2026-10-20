"""Runtime annotation responsibilities and the shared semantic interface."""

import ast

import pytest
from archunitpython import assert_passes, project_files, project_layers
from archunitpython.layers.fluentapi.layers import LayeredArchitecture

from .definitions import SEMANTICS, TYPE_FORGE
from .helpers import ArchModule


def _interface_layer(module: ArchModule) -> str:
    return f"{module.name}.{module.interface.name}"


@pytest.fixture
def architecture() -> LayeredArchitecture:
    architecture = project_layers(TYPE_FORGE.path.parent.as_posix())
    for layer in (
        *TYPE_FORGE.mod("pydantic").layers,
        TYPE_FORGE.file("utils.error_handling"),
        TYPE_FORGE.file("_type_function"),
        TYPE_FORGE.file("_capture"),
    ):
        architecture.layer(layer.name).defined_by(layer.pattern)

    # Distinguish the three __init__.py owners instead of overwriting one layer.
    for module in (TYPE_FORGE.mod("pydantic"), SEMANTICS, TYPE_FORGE):
        architecture.layer(_interface_layer(module)).defined_by(
            module.interface.pattern
        )

    return architecture


def test_runtime_dependencies_keep_policy_and_emission_separate(
    architecture: LayeredArchitecture,
) -> None:
    integration = TYPE_FORGE.mod("pydantic")

    def file(name: str) -> str:
        return integration.file(name).name

    shared = (_interface_layer(SEMANTICS), TYPE_FORGE.file("utils.error_handling").name)
    rule = (
        architecture.where_layer(_interface_layer(integration))
        .may_only_depend_on_layers(file("_annotation"), file("_markers"))
        .where_layer(file("_markers"))
        .may_only_depend_on_layers()
        .where_layer(file("_errors"))
        .may_only_depend_on_layers()
        .where_layer(file("_policy"))
        .may_only_depend_on_layers(file("_errors"), _interface_layer(SEMANTICS))
        .where_layer(file("_type_system"))
        .may_only_depend_on_layers(file("_records"), file("_policy"), *shared)
        .where_layer(file("_records"))
        .may_only_depend_on_layers(*shared)
        .where_layer(file("_frontend"))
        .may_only_depend_on_layers(
            file("_errors"),
            file("_policy"),
            file("_type_system"),
            file("_markers"),
            _interface_layer(TYPE_FORGE),
            TYPE_FORGE.file("_type_function").name,
            TYPE_FORGE.file("_capture").name,
            *shared,
        )
        .where_layer(file("_emission"))
        .may_only_depend_on_layers(file("_errors"), file("_type_system"), *shared)
        .where_layer(file("_observation"))
        .may_only_depend_on_layers(file("_policy"), file("_type_system"), *shared)
        .where_layer(file("_evaluation"))
        .may_only_depend_on_layers(
            file("_errors"),
            file("_frontend"),
            file("_policy"),
            file("_records"),
            file("_type_system"),
            *shared,
        )
        .where_layer(file("_deferred"))
        .may_only_depend_on_layers(
            file("_frontend"),
            file("_evaluation"),
            file("_emission"),
            file("_observation"),
            file("_policy"),
            file("_type_system"),
            *shared,
        )
        .where_layer(file("_compile"))
        .may_only_depend_on_layers(
            file("_frontend"),
            file("_policy"),
            file("_type_system"),
            file("_emission"),
            file("_errors"),
            file("_evaluation"),
            file("_deferred"),
            _interface_layer(TYPE_FORGE),
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


def test_core_schema_construction_stays_in_emission_modules() -> None:
    integration = TYPE_FORGE.mod("pydantic")
    emitters = {integration.file("_emission").path, integration.file("_deferred").path}
    for source in integration.path.rglob("*.py"):
        if source in emitters:
            continue

        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module == "pydantic_core" or node.module.startswith(
                    "pydantic_core."
                ):
                    assert node.module == "pydantic_core", source
                    assert all(name.name == "CoreSchema" for name in node.names), source

            elif isinstance(node, ast.Import):
                assert not any(
                    name.name == "pydantic_core"
                    or name.name.startswith("pydantic_core.")
                    for name in node.names
                ), source
