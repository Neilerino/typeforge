"""Render fully prepared stub IR as deterministic Python text."""

from typeforge.compiler.emission._models import EmissionError
from typeforge.compiler.emission._python import (
    emit_stub_module,
    emit_type_expression,
    emit_type_parameter,
)

__all__ = [
    "EmissionError",
    "emit_stub_module",
    "emit_type_expression",
    "emit_type_parameter",
]
