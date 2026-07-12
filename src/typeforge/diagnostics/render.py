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
