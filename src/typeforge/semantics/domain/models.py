"""Backend-neutral data shared by semantic adapters."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeIs


class RecordFamily(StrEnum):
    """Record construction semantics preserved across adapters."""

    TYPED_DICT = "typed_dict"
    DATACLASS = "dataclass"
    PROTOCOL = "protocol"
    CLASS = "class"
    ATTRS = "attrs"
    VALIDATION_MODEL = "validation_model"


@dataclass(frozen=True, slots=True)
class RecordField[T]:
    """One field in a family-aware record shape."""

    name: str
    value: T
    required: bool = True
    readonly: bool = False


@dataclass(frozen=True, slots=True)
class RecordShape[T]:
    """A record shape whose family controls construction semantics."""

    family: RecordFamily
    name: str | None
    fields: tuple[RecordField[T], ...]


@dataclass(frozen=True, slots=True)
class TypeReference[T]:
    """A backend-specific type referenced by a semantic expression."""

    value: T


@dataclass(frozen=True, slots=True)
class ParameterizedTypeShape[T]:
    """The origin and type arguments inspected from a backend type."""

    origin: T
    arguments: tuple[T, ...]


@dataclass(frozen=True, slots=True)
class ExactTypePattern[T]:
    """A structural pattern that matches one backend type exactly."""

    value: T


@dataclass(frozen=True, slots=True)
class CaptureValuePattern:
    """The structural pattern position bound to authored `Value`."""


@dataclass(frozen=True, slots=True)
class ParameterizedTypePattern[T]:
    """A structural pattern for a parameterized type."""

    origin: T
    arguments: tuple[TypePattern[T], ...]


@dataclass(frozen=True, slots=True)
class UnionExpression[T]:
    members: tuple[Expression[T], ...]


@dataclass(frozen=True, slots=True)
class InputReference:
    pass


@dataclass(frozen=True, slots=True)
class KeyReference:
    pass


@dataclass(frozen=True, slots=True)
class ValueReference:
    pass


@dataclass(frozen=True, slots=True)
class ParameterizedTypeTemplate[T]:
    """A parameterized output type awaiting contextual substitution."""

    origin: T
    arguments: tuple[TypeTemplate[T], ...]


@dataclass(frozen=True, slots=True)
class FieldName:
    value: str


@dataclass(frozen=True, slots=True)
class EqualExpression[T]:
    left: Expression[T]
    right: Expression[T]


@dataclass(frozen=True, slots=True)
class AssignableExpression[T]:
    source: Expression[T]
    target: Expression[T]


@dataclass(frozen=True, slots=True)
class AllExpression[T]:
    conditions: tuple[Expression[T], ...]


@dataclass(frozen=True, slots=True)
class AnyExpression[T]:
    conditions: tuple[Expression[T], ...]


@dataclass(frozen=True, slots=True)
class NotExpression[T]:
    condition: Expression[T]


@dataclass(frozen=True, slots=True)
class CaseExpression[T]:
    test: Expression[T] | TypePattern[T]
    output: Expression[T]


@dataclass(frozen=True, slots=True)
class MapExpression[T]:
    subject: Expression[T]
    cases: tuple[CaseExpression[T], ...]
    default: Expression[T] | None = None


@dataclass(frozen=True, slots=True)
class FieldExpression[T]:
    name: Expression[T]
    value: Expression[T]


@dataclass(frozen=True, slots=True)
class OptionalFieldExpression[T]:
    name: Expression[T]
    value: Expression[T]


@dataclass(frozen=True, slots=True)
class ReadonlyFieldExpression[T]:
    name: Expression[T]
    value: Expression[T]


@dataclass(frozen=True, slots=True)
class DropExpression:
    pass


@dataclass(frozen=True, slots=True)
class MapFieldsExpression[T]:
    record: Expression[T]
    transform: Expression[T]
    output_name: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedType[T]:
    """A backend-specific type resolved by semantic evaluation."""

    value: T


@dataclass(frozen=True, slots=True)
class DroppedField:
    pass


@dataclass(frozen=True, slots=True)
class EvaluationContext[T]:
    """Bindings available while evaluating nested expressions."""

    key: str | None = None
    value: ResolvedType[T] | None = None
    capture: ResolvedType[T] | None = None
    input_type: ResolvedType[T] | None = None


@dataclass(frozen=True, slots=True)
class DeferredMap[T]:
    """A Map whose ordered case selection must wait for Input."""

    cases: tuple[CaseExpression[T], ...]
    default: Expression[T] | None
    context: EvaluationContext[T]
    possible_output: ResolvedType[T]


type EvaluationValue[T] = (
    ResolvedType[T]
    | RecordShape[T]
    | RecordField[T]
    | FieldName
    | DroppedField
    | DeferredMap[T]
    | bool
)


type Expression[T] = (
    TypeReference[T]
    | UnionExpression[T]
    | InputReference
    | KeyReference
    | ValueReference
    | ParameterizedTypeTemplate[T]
    | FieldName
    | EqualExpression[T]
    | AssignableExpression[T]
    | AllExpression[T]
    | AnyExpression[T]
    | NotExpression[T]
    | MapExpression[T]
    | FieldExpression[T]
    | OptionalFieldExpression[T]
    | ReadonlyFieldExpression[T]
    | DropExpression
    | MapFieldsExpression[T]
)

type BooleanExpression[T] = (
    EqualExpression[T]
    | AssignableExpression[T]
    | AllExpression[T]
    | AnyExpression[T]
    | NotExpression[T]
)

type TypePattern[T] = (
    ExactTypePattern[T] | CaptureValuePattern | ParameterizedTypePattern[T]
)


type TypeTemplate[T] = TypeReference[T] | ValueReference | ParameterizedTypeTemplate[T]


def type_ref(value: object, /) -> TypeReference[object]:
    """Reference a Python typing object in the shared runtime type domain."""
    return TypeReference(value)


def is_bool_expr[T](
    expression: Expression[T] | TypePattern[T],
) -> TypeIs[BooleanExpression[T]]:
    return isinstance(
        expression,
        EqualExpression
        | AssignableExpression
        | AllExpression
        | AnyExpression
        | NotExpression,
    )


def is_pattern_expr[T](
    expression: Expression[T] | TypePattern[T],
) -> TypeIs[TypePattern[T]]:
    return isinstance(
        expression,
        ExactTypePattern | CaptureValuePattern | ParameterizedTypePattern,
    )
