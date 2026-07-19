"""Validated, role-aware representations of Typeforge marker expressions."""

from dataclasses import dataclass

from typeforge.compiler.model import (
    MarkerKind,
    MarkerTypeExpression,
)
from typeforge.compiler.model import (
    TypeExpression as SourceTypeExpression,
)


@dataclass(frozen=True, slots=True)
class MarkerArity:
    minimum: int
    maximum: int | None
    requirement: str


MARKER_SIGNATURES = {
    MarkerKind.EACH: MarkerArity(1, 1, "one type argument"),
    MarkerKind.COLLECT: MarkerArity(1, 1, "one type argument"),
    MarkerKind.ASSIGNABLE: MarkerArity(2, 2, "two type arguments"),
    MarkerKind.EQUAL: MarkerArity(2, 2, "two type arguments"),
    MarkerKind.ALL: MarkerArity(0, None, "zero or more type arguments"),
    MarkerKind.ANY: MarkerArity(0, None, "zero or more type arguments"),
    MarkerKind.NOT: MarkerArity(1, 1, "one type argument"),
    MarkerKind.MAP: MarkerArity(
        2,
        None,
        "a subject and at least one Case or Default",
    ),
    MarkerKind.CASE: MarkerArity(2, 2, "two type arguments"),
    MarkerKind.DEFAULT: MarkerArity(1, 1, "one type argument"),
    MarkerKind.MAP_FIELDS: MarkerArity(2, 2, "two type arguments"),
    MarkerKind.FIELD: MarkerArity(2, 2, "two type arguments"),
    MarkerKind.OPTIONAL_FIELD: MarkerArity(2, 2, "two type arguments"),
    MarkerKind.READONLY_FIELD: MarkerArity(2, 2, "two type arguments"),
    MarkerKind.DROP: MarkerArity(0, 0, "no type arguments"),
    MarkerKind.KEY: MarkerArity(0, 0, "no type arguments"),
    MarkerKind.VALUE: MarkerArity(0, 0, "no type arguments"),
}


@dataclass(frozen=True, slots=True)
class MarkerNormalizationError(Exception):
    source: str
    message: str


@dataclass(frozen=True, slots=True)
class EachMarker:
    source: str
    item: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class CollectMarker:
    source: str
    item: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class AssignableMarker:
    source: str
    left: SourceTypeExpression
    right: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class EqualMarker:
    source: str
    left: SourceTypeExpression
    right: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class AllMarker:
    source: str
    items: tuple[SourceTypeExpression, ...]


@dataclass(frozen=True, slots=True)
class AnyMarker:
    source: str
    items: tuple[SourceTypeExpression, ...]


@dataclass(frozen=True, slots=True)
class NotMarker:
    source: str
    item: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class CaseMarker:
    source: str
    test: SourceTypeExpression
    output: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class DefaultMarker:
    source: str
    output: SourceTypeExpression


type MapEntryMarker = CaseMarker | DefaultMarker


@dataclass(frozen=True, slots=True)
class MapMarker:
    source: str
    subject: SourceTypeExpression
    entries: tuple[MapEntryMarker, ...]


@dataclass(frozen=True, slots=True)
class MapFieldsMarker:
    source: str
    record: SourceTypeExpression
    transform: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class FieldMarker:
    source: str
    key: SourceTypeExpression
    value: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class OptionalFieldMarker:
    source: str
    key: SourceTypeExpression
    value: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class ReadonlyFieldMarker:
    source: str
    key: SourceTypeExpression
    value: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class DropMarker:
    source: str


@dataclass(frozen=True, slots=True)
class KeyMarker:
    source: str


@dataclass(frozen=True, slots=True)
class ValueMarker:
    source: str


type NormalizedMarker = (
    EachMarker
    | CollectMarker
    | AssignableMarker
    | EqualMarker
    | AllMarker
    | AnyMarker
    | NotMarker
    | MapMarker
    | CaseMarker
    | DefaultMarker
    | MapFieldsMarker
    | FieldMarker
    | OptionalFieldMarker
    | ReadonlyFieldMarker
    | DropMarker
    | KeyMarker
    | ValueMarker
)


def normalize_marker(expression: MarkerTypeExpression) -> NormalizedMarker:
    _validate_arity(expression)
    source = expression.source
    arguments = expression.arguments
    match expression.marker:
        case MarkerKind.EACH:
            return EachMarker(source, arguments[0])
        case MarkerKind.COLLECT:
            return CollectMarker(source, arguments[0])
        case MarkerKind.ASSIGNABLE:
            return AssignableMarker(source, arguments[0], arguments[1])
        case MarkerKind.EQUAL:
            return EqualMarker(source, arguments[0], arguments[1])
        case MarkerKind.ALL:
            for argument in arguments:
                _validate_predicate_role(argument)
            return AllMarker(source, arguments)
        case MarkerKind.ANY:
            for argument in arguments:
                _validate_predicate_role(argument)
            return AnyMarker(source, arguments)
        case MarkerKind.NOT:
            _validate_predicate_role(arguments[0])
            return NotMarker(source, arguments[0])
        case MarkerKind.MAP:
            return _normalize_map(source, arguments)
        case MarkerKind.CASE:
            if isinstance(arguments[0], MarkerTypeExpression) and arguments[
                0
            ].marker in {
                MarkerKind.ASSIGNABLE,
                MarkerKind.EQUAL,
                MarkerKind.ALL,
                MarkerKind.ANY,
                MarkerKind.NOT,
            }:
                _validate_predicate_role(arguments[0])
            return CaseMarker(source, arguments[0], arguments[1])
        case MarkerKind.DEFAULT:
            return DefaultMarker(source, arguments[0])
        case MarkerKind.MAP_FIELDS:
            return MapFieldsMarker(source, arguments[0], arguments[1])
        case MarkerKind.FIELD:
            return FieldMarker(source, arguments[0], arguments[1])
        case MarkerKind.OPTIONAL_FIELD:
            return OptionalFieldMarker(source, arguments[0], arguments[1])
        case MarkerKind.READONLY_FIELD:
            return ReadonlyFieldMarker(source, arguments[0], arguments[1])
        case MarkerKind.DROP:
            return DropMarker(source)
        case MarkerKind.KEY:
            return KeyMarker(source)
        case MarkerKind.VALUE:
            return ValueMarker(source)


def _validate_arity(expression: MarkerTypeExpression) -> None:
    arity = MARKER_SIGNATURES[expression.marker]
    count = len(expression.arguments)
    if count < arity.minimum or (arity.maximum is not None and count > arity.maximum):
        raise MarkerNormalizationError(
            expression.source,
            f"{expression.marker.value} requires {arity.requirement}",
        )


def _normalize_map(
    source: str,
    arguments: tuple[SourceTypeExpression, ...],
) -> MapMarker:
    entries: list[MapEntryMarker] = []
    default_seen = False
    for expression in arguments[1:]:
        if not isinstance(expression, MarkerTypeExpression):
            raise MarkerNormalizationError(
                expression.source,
                "Map entries must be Case[Test, Output] or Default[Output]",
            )
        entry = normalize_marker(expression)
        if not isinstance(entry, CaseMarker | DefaultMarker):
            raise MarkerNormalizationError(
                expression.source,
                "Map entries must be Case[Test, Output] or Default[Output]",
            )
        if isinstance(entry, DefaultMarker):
            if default_seen:
                raise MarkerNormalizationError(
                    expression.source,
                    "Map may contain at most one Default",
                )
            default_seen = True
        entries.append(entry)
    return MapMarker(source, arguments[0], tuple(entries))


def _validate_predicate_role(expression: SourceTypeExpression) -> None:
    if not isinstance(expression, MarkerTypeExpression):
        raise MarkerNormalizationError(
            expression.source,
            "condition must be a Typeforge predicate",
        )
    marker = normalize_marker(expression)
    if not isinstance(
        marker,
        EqualMarker | AssignableMarker | AllMarker | AnyMarker | NotMarker,
    ):
        raise MarkerNormalizationError(
            expression.source,
            f"{expression.marker.value} is not a predicate",
        )
