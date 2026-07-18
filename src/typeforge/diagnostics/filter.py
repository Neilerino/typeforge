from typeforge.analysis.model import Diagnostic

_IMPLEMENTATION_RETURN_CODES = frozenset({"bad-return", "return-value"})


def deduplicate_return_diagnostics(
    diagnostics: tuple[Diagnostic, ...],
) -> tuple[Diagnostic, ...]:
    verified = {
        (item.path, item.span.start.offset)
        for item in diagnostics
        if item.provenance is not None
    }
    return tuple(
        item
        for item in diagnostics
        if not (
            item.provenance is None
            and item.code in _IMPLEMENTATION_RETURN_CODES
            and (item.path, item.span.start.offset) in verified
        )
    )
