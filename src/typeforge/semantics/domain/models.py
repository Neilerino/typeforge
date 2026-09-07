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
    metadata: tuple[T, ...] = ()


@dataclass(frozen=True, slots=True)
class AnnotatedExpression[T]:
    """Backend-owned metadata attached to a type or a synthesized record."""

    origin: T
    value: Expression[T]
    metadata: tuple[T, ...]


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
    arguments: tuple[Expression[T], ...]


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
class TypeSymbol:
    """An authored type parameter identified within its declaring scope."""

    scope: tuple[str, ...]
    name: str


@dataclass(frozen=True, slots=True)
class UnresolvedType[T]:
    """A backend type with symbolic or partially unresolved structural provenance."""

    value: T
    provenance: TypeSymbol | ParameterizedTypeShape[TypeValue[T]] | UnionTypeShape[T]


@dataclass(frozen=True, slots=True)
class UnionTypeShape[T]:
    """Members of a definite union with unresolved static positions."""

    members: tuple[TypeValue[T], ...]


@dataclass(frozen=True, slots=True)
class IndeterminateType[T]:
    """Possible alternatives of a static selection, not a definite union type.

    Equal alternative summaries do not establish identity between selections.
    Selection and normalization policy belongs to semantic evaluation.
    """

    possible_output: ResolvedType[T]
    alternatives: tuple[TypeValue[T], ...]


type TypeValue[T] = ResolvedType[T] | UnresolvedType[T] | IndeterminateType[T]


@dataclass(frozen=True, slots=True)
class TypeValueReference[T]:
    """Reference a static value while retaining its resolution provenance."""

    value: TypeValue[T]


@dataclass(frozen=True, slots=True)
class IndeterminateCondition:
    """A condition whose truth depends on unresolved static information."""


type Condition = bool | IndeterminateCondition


@dataclass(frozen=True, slots=True)
class DroppedField:
    pass


class EvaluationMode(StrEnum):
    """Whether a path is reached or explored for its possible output."""

    DEFINITE = "definite"
    SPECULATIVE = "speculative"


class NoMatchDecision(StrEnum):
    """Accept the language's Never output, or reject an exhausted selection."""

    ACCEPT = "accept"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class EvaluationContext[T]:
    """Immutable bindings and reachability for a nested evaluation."""

    key: str | None = None
    value: TypeValue[T] | None = None
    capture: TypeValue[T] | None = None
    input_type: TypeValue[T] | None = None
    mode: EvaluationMode = EvaluationMode.DEFINITE


@dataclass(frozen=True, slots=True)
class DeferredMap[T]:
    """A Map whose ordered case selection must wait for Input."""

    cases: tuple[CaseExpression[T], ...]
    default: Expression[T] | None
    context: EvaluationContext[T]
    possible_output: ResolvedType[T]


@dataclass(frozen=True, slots=True)
class MapNoMatch[T]:
    """An evaluated Map path exhausted its cases without an authored default."""

    expression: MapExpression[T]
    subject: EvaluationValue[T]
    context: EvaluationContext[T]


type EvaluationValue[T] = (
    TypeValue[T]
    | RecordShape[T]
    | RecordField[T]
    | FieldName
    | DroppedField
    | DeferredMap[T]
    | bool
    | IndeterminateCondition
)


type Expression[T] = (
    TypeReference[T]
    | AnnotatedExpression[T]
    | TypeValueReference[T]
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
    ExactTypePattern[T]
    | CaptureValuePattern
    | ParameterizedTypePattern[T]
    | TypeValueReference[T]
)


type TypeTemplate[T] = (
    TypeReference[T]
    | TypeValueReference[T]
    | ValueReference
    | ParameterizedTypeTemplate[T]
    | UnionExpression[T]
)


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
        ExactTypePattern
        | CaptureValuePattern
        | ParameterizedTypePattern
        | TypeValueReference,
    )
