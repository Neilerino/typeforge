"""Type facts from one authored snapshot, without executing its classes."""

from dataclasses import dataclass

from typeforge.compiler.semantic_adapter import NamedType, SemanticEnvironment
from typeforge.compiler.source import SourceModule, TypeAliasDeclaration


@dataclass(frozen=True, slots=True)
class SourceTypeContext:
    aliases: tuple[TypeAliasDeclaration, ...]
    types: SemanticEnvironment
    record_aliases: frozenset[str] = frozenset()
    record_types: frozenset[str] = frozenset()


def class_type_environment(module: SourceModule) -> SemanticEnvironment:
    classes = {
        declaration.name: declaration
        for declaration in module.classes
        if len(declaration.qualified_name) == 1
    }
    types: list[tuple[str, NamedType]] = []
    for name, declaration in classes.items():
        pending = [base.source for base in declaration.bases]
        ancestors: list[str] = []
        while pending:
            base = pending.pop(0)
            if base == name or base in ancestors:
                continue

            ancestors.append(base)
            parent = classes.get(base)
            if parent is not None:
                pending.extend(item.source for item in parent.bases)

        types.append((name, NamedType(name, tuple(ancestors))))

    return tuple(types)
