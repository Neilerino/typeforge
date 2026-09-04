"""Inspect and preserve the complete authored module surface."""

from typeforge.compiler.module_surface._inspection import inspect_module_surface
from typeforge.compiler.module_surface._models import (
    ModuleSurface,
    UnsupportedPublicDeclaration,
)

__all__ = [
    "ModuleSurface",
    "UnsupportedPublicDeclaration",
    "inspect_module_surface",
]
