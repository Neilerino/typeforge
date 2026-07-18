from pathlib import Path

from typeforge.analysis.model import (
    Diagnostic,
    DiagnosticSeverity,
    ReturnCheckProvenance,
    SourcePosition,
    SourceSpan,
)
from typeforge.diagnostics.filter import deduplicate_return_diagnostics
from typeforge.diagnostics.render import render_return_check


def test_return_check_message_describes_authored_relationship() -> None:
    provenance = ReturnCheckProvenance(
        callable_name=("Converter", "convert"),
        return_annotation="Result[T]",
        controller_parameter="value",
        narrowed_inputs=("int",),
        expected_types=("str",),
    )

    message = render_return_check(provenance, "bool is not assignable to str")

    assert message == (
        "Invalid return from `Converter.convert`\n\n"
        "`value` is narrowed to `int`, so `Result[T]` has a more specific "
        "requirement.\n\n"
        "Expected: `str`\n"
        "Checker detail: bool is not assignable to str"
    )


def test_generated_check_replaces_duplicate_implementation_return_error() -> None:
    position = SourcePosition(offset=12, line=1, column=4)
    span = SourceSpan(position, position)
    provenance = ReturnCheckProvenance(
        callable_name=("convert",),
        return_annotation="Result[T]",
        controller_parameter="value",
        narrowed_inputs=("int",),
        expected_types=("str",),
    )
    generated = Diagnostic(
        checker="pyrefly",
        path=Path("example.py"),
        span=span,
        severity=DiagnosticSeverity.ERROR,
        message="helpful",
        code="bad-assignment",
        provenance=provenance,
    )
    duplicate = Diagnostic(
        checker="pyrefly",
        path=Path("example.py"),
        span=span,
        severity=DiagnosticSeverity.ERROR,
        message="generated implementation union",
        code="bad-return",
    )

    assert deduplicate_return_diagnostics((generated, duplicate)) == (generated,)
