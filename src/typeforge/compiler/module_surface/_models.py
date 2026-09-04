"""Data and modeled failures produced by module-surface inspection."""

from dataclasses import dataclass
from pathlib import Path

from typeforge.compiler.stub_ir import ModuleImport, VariableDeclaration


@dataclass(frozen=True, slots=True)
class UnsupportedPublicDeclaration:
    path: Path
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class ModuleSurface:
    declarations: tuple[VariableDeclaration, ...]
    imports: tuple[ModuleImport, ...]
