from typeforge.analysis.model import ReturnCheckProvenance
from typeforge.diagnostics.model import Explanation


def render_compact(explanation: Explanation) -> str:
    received = ", ".join(f"`{item}`" for item in explanation.received)
    if not received:
        received = "no arguments"
    expected = ", ".join(f"`{item}`" for item in explanation.expected)
    if not expected:
        expected = "no arguments"
    lines = [
        explanation.title,
        "",
        f"Received: {received}",
        f"Expected: {expected}",
    ]
    if explanation.reasons:
        lines.extend(("", *explanation.reasons))
    return "\n".join(lines)


def render_return_check(
    provenance: ReturnCheckProvenance,
    checker_message: str,
) -> str:
    callable_name = ".".join(provenance.callable_name)
    expected = ", ".join(f"`{item}`" for item in provenance.expected_types)
    if len(provenance.expected_types) > 1:
        expected_line = f"Expected on every possible path: {expected}"
    else:
        expected_line = f"Expected: {expected}"
    lines = [f"Invalid return from `{callable_name}`", ""]
    narrowed = ", ".join(f"`{item}`" for item in provenance.narrowed_inputs)
    if narrowed:
        lines.append(
            f"`{provenance.controller_parameter}` is narrowed to {narrowed}, so "
            f"`{provenance.return_annotation}` has a more specific requirement."
        )
        lines.append("")
    lines.extend((expected_line, f"Checker detail: {checker_message}"))
    return "\n".join(lines)
