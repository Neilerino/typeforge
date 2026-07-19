from pathlib import Path

import pytest

from typeforge.compiler._markers import (
    MARKER_SIGNATURES,
    MapMarker,
    MarkerNormalizationError,
    normalize_marker,
)
from typeforge.compiler.model import (
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    SourcePosition,
    SourceSpan,
)

SPAN = SourceSpan(Path("markers.py"), SourcePosition(1, 0), SourcePosition(1, 1))
ITEM = NameTypeExpression("T", SPAN, ("T",), None)


@pytest.mark.parametrize("kind", tuple(MarkerKind))
def test_every_marker_has_one_authoritative_valid_arity(kind: MarkerKind) -> None:
    arity = MARKER_SIGNATURES[kind]
    count = arity.minimum
    arguments: tuple[NameTypeExpression | MarkerTypeExpression, ...] = tuple(
        ITEM for _ in range(count)
    )
    if kind is MarkerKind.MAP:
        arguments = (ITEM, marker(MarkerKind.CASE, ITEM, ITEM))
    elif kind is MarkerKind.NOT:
        arguments = (marker(MarkerKind.EQUAL, ITEM, ITEM),)

    assert normalize_marker(marker(kind, *arguments))


@pytest.mark.parametrize(
    ("kind", "arguments", "requirement"),
    (
        (MarkerKind.KEY, (ITEM,), "no type arguments"),
        (MarkerKind.EACH, (), "one type argument"),
        (MarkerKind.EQUAL, (ITEM,), "two type arguments"),
        (
            MarkerKind.MAP,
            (ITEM,),
            "a subject and at least one Case or Default",
        ),
    ),
)
def test_invalid_arities_use_the_shared_signature_table(
    kind: MarkerKind,
    arguments: tuple[NameTypeExpression, ...],
    requirement: str,
) -> None:
    with pytest.raises(MarkerNormalizationError) as raised:
        normalize_marker(marker(kind, *arguments))

    assert raised.value.message == f"{kind.value} requires {requirement}"


def test_map_normalization_validates_entry_roles_and_duplicate_defaults() -> None:
    with pytest.raises(MarkerNormalizationError, match="Map entries must be"):
        normalize_marker(marker(MarkerKind.MAP, ITEM, marker(MarkerKind.KEY)))

    with pytest.raises(MarkerNormalizationError, match="at most one Default"):
        normalize_marker(
            marker(
                MarkerKind.MAP,
                ITEM,
                marker(MarkerKind.DEFAULT, ITEM),
                marker(MarkerKind.DEFAULT, ITEM),
            )
        )

    normalized = normalize_marker(
        marker(MarkerKind.MAP, ITEM, marker(MarkerKind.CASE, ITEM, ITEM))
    )
    assert isinstance(normalized, MapMarker)


def test_condition_markers_validate_nested_predicate_roles() -> None:
    with pytest.raises(MarkerNormalizationError, match="Key is not a predicate"):
        normalize_marker(
            marker(
                MarkerKind.MAP,
                ITEM,
                marker(
                    MarkerKind.CASE,
                    marker(MarkerKind.ALL, marker(MarkerKind.KEY)),
                    ITEM,
                ),
            )
        )


def marker(
    kind: MarkerKind,
    *arguments: NameTypeExpression | MarkerTypeExpression,
) -> MarkerTypeExpression:
    return MarkerTypeExpression(
        kind.value,
        SPAN,
        kind,
        arguments,
    )
