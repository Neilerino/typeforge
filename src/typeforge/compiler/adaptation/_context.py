"""Type facts from one authored snapshot, without executing its classes."""

from dataclasses import dataclass

from typeforge.compiler.semantic_adapter import (
    SemanticEnvironment,
    named_type_environment,
)
from typeforge.compiler.source import SourceModule, TypeAliasDeclaration


@dataclass(frozen=True, slots=True)
class SourceTypeContext:
    aliases: tuple[TypeAliasDeclaration, ...]
    types: SemanticEnvironment
    record_aliases: frozenset[str] = frozenset()
    record_types: frozenset[str] = frozenset()


def class_type_environment(module: SourceModule) -> SemanticEnvironment:
    classes = tuple(
        (declaration.name, tuple(base.source for base in declaration.bases))
        for declaration in module.classes
        if len(declaration.qualified_name) == 1
    )
    return named_type_environment(classes)
