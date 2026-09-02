"""Dependency rules for the shared semantics module."""

import re

import pytest
from archunitpython import assert_passes, project_files, project_layers
from archunitpython.layers.fluentapi.layers import LayeredArchitecture

from .consts import STDLIB_DEPENDENCY, STDLIB_MODULES
from .definitions import SEMANTICS, TYPE_FORGE
from .helpers import ArchFile, ArchModule

SEMANTICS_EXTERNAL_DEPENDENCY = re.compile(
    rf"^(?:(?:{STDLIB_MODULES})(?:\..*)?|returns(?:\..*)?)$"
)


@pytest.fixture
def semantics() -> ArchModule:
    return SEMANTICS


@pytest.fixture
def typeforge() -> ArchModule:
    return TYPE_FORGE


@pytest.fixture
def source_root(typeforge: ArchModule) -> str:
    return typeforge.path.parent.as_posix()


@pytest.fixture
def architecture(typeforge: ArchModule) -> LayeredArchitecture:
    architecture = project_layers(typeforge.path.parent.as_posix())
    for layer in typeforge.layers:
        architecture.layer(layer.name).defined_by(layer.pattern)
    return architecture


@pytest.fixture
def domain(semantics: ArchModule) -> ArchModule:
    return semantics.mod("domain")


@pytest.fixture
def protocols(semantics: ArchModule) -> ArchFile:
    return semantics.file("protocols")


@pytest.fixture
def map_evaluation(semantics: ArchModule) -> ArchFile:
    return semantics.file("map_evaluation")


@pytest.fixture
def evaluation(semantics: ArchModule) -> ArchFile:
    return semantics.file("evaluation")


@pytest.fixture
def interface(semantics: ArchModule) -> ArchFile:
    return semantics.interface


@pytest.fixture
def other_typeforge_modules(
    typeforge: ArchModule, semantics: ArchModule
) -> re.Pattern[str]:
    return typeforge.files_outside(semantics)


def test_semantics_dependencies_point_toward_the_domain(
    architecture: LayeredArchitecture,
    domain: ArchModule,
    protocols: ArchFile,
    map_evaluation: ArchFile,
    evaluation: ArchFile,
    interface: ArchFile,
) -> None:
    """Keep domain data independent and orchestration at the outer seam."""
    rule = (
        architecture.where_layer(domain.name)
        .may_only_depend_on_layers()
        .where_layer(protocols.name)
        .may_only_depend_on_layers(domain.name)
        .where_layer(map_evaluation.name)
        .may_only_depend_on_layers(domain.name, protocols.name)
        .where_layer(evaluation.name)
        .may_only_depend_on_layers(
            domain.name,
            protocols.name,
            map_evaluation.name,
        )
        .where_layer(interface.name)
        .may_only_depend_on_layers(domain.name, protocols.name, evaluation.name)
    )

    assert_passes(rule)


def test_typeforge_uses_the_semantics_package_interface(
    source_root: str,
    semantics: ArchModule,
    other_typeforge_modules: re.Pattern[str],
) -> None:
    rule = (
        project_files(source_root)
        .in_path(other_typeforge_modules)
        .should_not()
        .depend_on_files()
        .in_path(semantics.implementation_pattern)
        .because(
            "typeforge.semantics is the supported seam; its implementation is internal"
        )
    )

    assert_passes(rule)


def test_semantics_domain_only_depends_on_the_standard_library(
    source_root: str, domain: ArchModule
) -> None:
    rule = (
        project_files(source_root)
        .in_path(domain.pattern)
        .should()
        .depend_on_external_modules()
        .matching(STDLIB_DEPENDENCY)
        .because("domain data and assertions must remain backend-neutral")
    )

    assert_passes(rule)


def test_semantics_only_depends_on_returns_and_the_standard_library(
    source_root: str, semantics: ArchModule
) -> None:
    rule = (
        project_files(source_root)
        .in_path(semantics.pattern)
        .should()
        .depend_on_external_modules()
        .matching(SEMANTICS_EXTERNAL_DEPENDENCY)
        .because("frontend and backend libraries belong behind TypeSystem adapters")
    )

    assert_passes(rule)


def test_semantics_has_no_dependency_cycles(
    source_root: str, semantics: ArchModule
) -> None:
    rule = (
        project_files(source_root)
        .in_path(semantics.pattern)
        .should()
        .have_no_cycles()
        .because("the dependency direction must remain acyclic")
    )

    assert_passes(rule)
