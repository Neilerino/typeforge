"""Reflect TypedDict fields without choosing transformations or building schemas."""

from dataclasses import dataclass, replace
from typing import (
    Annotated,
    NotRequired,
    ReadOnly,
    Required,
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from typeforge import semantics as s
from typeforge.utils.error_handling import safe_result


@dataclass(frozen=True, slots=True)
class UnsupportedRecord(s.ExpectedRecordSemanticError):
    subject: object
    annotation: object = None


@dataclass(frozen=True, slots=True)
class UnresolvedRecordAnnotation(s.ExpectedRecordSemanticError):
    name: str


def parameters(value: object) -> tuple[TypeVar, ...]:
    origin = get_origin(value) or value
    declared: tuple[object, ...] = getattr(origin, "__parameters__", ())
    return tuple(parameter for parameter in declared if isinstance(parameter, TypeVar))


def bases(value: object) -> tuple[object, ...]:
    origin = get_origin(value) or value
    declared: tuple[object, ...] = getattr(origin, "__orig_bases__", ())
    return tuple(base for base in declared if is_typeddict(get_origin(base) or base))


@safe_result(errors=(s.SemanticIssue,))
def record_shape(value: object) -> s.RecordShape[object]:
    origin = get_origin(value) or value
    if not isinstance(origin, type) or not is_typeddict(origin):
        raise UnsupportedRecord(
            "The Pydantic integration supports TypedDict records only", value
        )

    try:
        annotations: dict[str, object] = get_type_hints(origin, include_extras=True)
    except NameError as error:
        raise UnresolvedRecordAnnotation(
            str(error), error.name or origin.__name__
        ) from error

    required: frozenset[str] = getattr(origin, "__required_keys__", frozenset())
    readonly: frozenset[str] = getattr(origin, "__readonly_keys__", frozenset())
    fields = tuple(
        _field(
            s.RecordField(
                name, annotation, required=name in required, readonly=name in readonly
            )
        )
        for name, annotation in annotations.items()
    )
    return s.RecordShape(
        s.RecordFamily.TYPED_DICT, f"{origin.__module__}.{origin.__qualname__}", fields
    )


def _field(field: s.RecordField[object]) -> s.RecordField[object]:
    origin = get_origin(field.value)
    arguments: tuple[object, ...] = get_args(field.value)
    if origin is Annotated:
        inner = _field(replace(field, value=arguments[0]))
        return replace(inner, value=Annotated[inner.value, *arguments[1:]])

    if origin in (Required, NotRequired, ReadOnly):
        return _field(
            replace(
                field,
                value=arguments[0],
                required=field.required if origin is ReadOnly else origin is Required,
                readonly=field.readonly or origin is ReadOnly,
            )
        )

    return field
