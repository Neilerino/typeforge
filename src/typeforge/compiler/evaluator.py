from dataclasses import dataclass
from enum import StrEnum

from returns.result import Failure, Result, Success

from typeforge.compiler.records import (
    NEVER,
    NamedType,
    NeverType,
    StaticType,
    TypedDictField,
    TypedDictShape,
    UnionType,
    union_of,
)


@dataclass(frozen=True, slots=True)
class Key:
    pass


@dataclass(frozen=True, slots=True)
class Value:
    pass


@dataclass(frozen=True, slots=True)
class FieldName:
    value: str


@dataclass(frozen=True, slots=True)
class Equal:
    left: Expression
    right: Expression


@dataclass(frozen=True, slots=True)
class Assignable:
    source: Expression
    target: Expression


@dataclass(frozen=True, slots=True)
class All:
    conditions: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class Any:
    conditions: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class Not:
    condition: Expression


@dataclass(frozen=True, slots=True)
class If:
    condition: Expression
    when_true: Expression
    when_false: Expression


@dataclass(frozen=True, slots=True)
class Case:
    input_type: Expression
    output_type: Expression


@dataclass(frozen=True, slots=True)
class Map:
    subject: Expression
    cases: tuple[Case, ...]
    default: Expression = NEVER


@dataclass(frozen=True, slots=True)
class Field:
    name: Expression
    value: Expression


@dataclass(frozen=True, slots=True)
class OptionalField:
    name: Expression
    value: Expression


@dataclass(frozen=True, slots=True)
class ReadonlyField:
    name: Expression
    value: Expression


@dataclass(frozen=True, slots=True)
class Drop:
    pass


@dataclass(frozen=True, slots=True)
class MapFields:
    record: Expression
    transform: Expression
    output_name: str | None = None


type Expression = (
    StaticType
    | Key
    | Value
    | FieldName
    | Equal
    | Assignable
    | All
    | Any
    | Not
    | If
    | Map
    | Field
    | OptionalField
    | ReadonlyField
    | Drop
    | MapFields
)


@dataclass(frozen=True, slots=True)
class DroppedField:
    pass


type EvaluationValue = StaticType | FieldName | bool | TypedDictField | DroppedField


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    key: str | None = None
    value: StaticType | None = None


EMPTY_CONTEXT = EvaluationContext()


class EvaluationErrorCode(StrEnum):
    UNBOUND_KEY = "unbound_key"
    UNBOUND_VALUE = "unbound_value"
    EXPECTED_TYPE = "expected_type"
    EXPECTED_CONDITION = "expected_condition"
    EXPECTED_FIELD_NAME = "expected_field_name"
    EXPECTED_FIELD = "expected_field"
    EXPECTED_TYPED_DICT = "expected_typed_dict"


@dataclass(frozen=True, slots=True)
class EvaluationError:
    code: EvaluationErrorCode
    message: str


def evaluate(
    expression: Expression, context: EvaluationContext = EMPTY_CONTEXT
) -> Result[EvaluationValue, EvaluationError]:
    if isinstance(expression, (NamedType, NeverType, UnionType, TypedDictShape)):
        return Success(expression)
    if isinstance(expression, FieldName):
        return Success(expression)
    if isinstance(expression, Key):
        if context.key is None:
            return _error(EvaluationErrorCode.UNBOUND_KEY, "Key requires MapFields")
        return Success(FieldName(context.key))
    if isinstance(expression, Value):
        if context.value is None:
            return _error(EvaluationErrorCode.UNBOUND_VALUE, "Value requires MapFields")
        return Success(context.value)
    if isinstance(expression, Equal):
        return _evaluate_equal(expression, context)
    if isinstance(expression, Assignable):
        return _evaluate_assignable(expression, context)
    if isinstance(expression, All):
        return _evaluate_all(expression, context)
    if isinstance(expression, Any):
        return _evaluate_any(expression, context)
    if isinstance(expression, Not):
        return _evaluate_not(expression, context)
    if isinstance(expression, If):
        return _evaluate_if(expression, context)
    if isinstance(expression, Map):
        return _evaluate_map(expression, context)
    if isinstance(expression, (Field, OptionalField, ReadonlyField)):
        return _evaluate_field(expression, context)
    if isinstance(expression, MapFields):
        mapped = evaluate_map_fields(expression, context)
        return mapped
    return Success(DroppedField())


def evaluate_map_fields(
    expression: MapFields, context: EvaluationContext = EMPTY_CONTEXT
) -> Result[TypedDictShape, EvaluationError]:
    record_result = evaluate(expression.record, context)
    if isinstance(record_result, Failure):
        return record_result
    record = record_result.unwrap()
    if not isinstance(record, TypedDictShape):
        return _error(
            EvaluationErrorCode.EXPECTED_TYPED_DICT,
            "MapFields record must evaluate to a TypedDictShape",
        )

    fields: list[TypedDictField] = []
    for source_field in record.fields:
        field_context = EvaluationContext(source_field.name, source_field.value)
        field_result = evaluate(expression.transform, field_context)
        if isinstance(field_result, Failure):
            return field_result
        field = field_result.unwrap()
        if isinstance(field, DroppedField):
            continue
        if not isinstance(field, TypedDictField):
            return _error(
                EvaluationErrorCode.EXPECTED_FIELD,
                "MapFields transform must evaluate to a field or Drop",
            )
        fields.append(field)
    return Success(
        TypedDictShape(
            expression.output_name or record.name,
            tuple(fields),
        )
    )


def _evaluate_equal(
    expression: Equal, context: EvaluationContext
) -> Result[EvaluationValue, EvaluationError]:
    return Result.do(
        left_value == right_value
        for left_value in evaluate(expression.left, context)
        for right_value in evaluate(expression.right, context)
    )


def _evaluate_assignable(
    expression: Assignable, context: EvaluationContext
) -> Result[EvaluationValue, EvaluationError]:
    return Result.do(
        _is_assignable(source_type, target_type)
        for source_type in _evaluate_type(expression.source, context)
        for target_type in _evaluate_type(expression.target, context)
    )


def _evaluate_all(
    expression: All, context: EvaluationContext
) -> Result[EvaluationValue, EvaluationError]:
    for condition in expression.conditions:
        result = _evaluate_condition(condition, context)
        if isinstance(result, Failure):
            return result
        if not result.unwrap():
            return Success(False)
    return Success(True)


def _evaluate_any(
    expression: Any, context: EvaluationContext
) -> Result[EvaluationValue, EvaluationError]:
    for condition in expression.conditions:
        result = _evaluate_condition(condition, context)
        if isinstance(result, Failure):
            return result
        if result.unwrap():
            return Success(True)
    return Success(False)


def _evaluate_not(
    expression: Not, context: EvaluationContext
) -> Result[EvaluationValue, EvaluationError]:
    return _evaluate_condition(expression.condition, context).map(
        lambda value: not value
    )


def _evaluate_if(
    expression: If, context: EvaluationContext
) -> Result[EvaluationValue, EvaluationError]:
    return Result.do(
        result
        for value in _evaluate_condition(expression.condition, context)
        for result in evaluate(
            expression.when_true if value else expression.when_false,
            context,
        )
    )


def _evaluate_map(
    expression: Map, context: EvaluationContext
) -> Result[EvaluationValue, EvaluationError]:
    subject = _evaluate_type(expression.subject, context)
    if isinstance(subject, Failure):
        return subject
    subject_type = subject.unwrap()
    members = (
        subject_type.members if isinstance(subject_type, UnionType) else (subject_type,)
    )
    outputs: list[StaticType] = []
    for member in members:
        output = _map_member(member, expression.cases, expression.default, context)
        if isinstance(output, Failure):
            return output
        outputs.append(output.unwrap())
    return Success(union_of(*outputs))


def _map_member(
    subject: StaticType,
    cases: tuple[Case, ...],
    default: Expression,
    context: EvaluationContext,
) -> Result[StaticType, EvaluationError]:
    for case in cases:
        input_type = _evaluate_type(case.input_type, context)
        if isinstance(input_type, Failure):
            return input_type
        if subject == input_type.unwrap():
            return _evaluate_type(case.output_type, context)
    return _evaluate_type(default, context)


def _evaluate_field(
    expression: Field | OptionalField | ReadonlyField,
    context: EvaluationContext,
) -> Result[EvaluationValue, EvaluationError]:
    name = evaluate(expression.name, context)
    if isinstance(name, Failure):
        return name
    field_name = name.unwrap()
    if not isinstance(field_name, FieldName):
        return _error(
            EvaluationErrorCode.EXPECTED_FIELD_NAME,
            "field name must evaluate to FieldName",
        )
    value = _evaluate_type(expression.value, context)
    if isinstance(value, Failure):
        return value
    return Success(
        TypedDictField(
            field_name.value,
            value.unwrap(),
            required=not isinstance(expression, OptionalField),
            readonly=isinstance(expression, ReadonlyField),
        )
    )


def _evaluate_condition(
    expression: Expression, context: EvaluationContext
) -> Result[bool, EvaluationError]:
    result = evaluate(expression, context)
    if isinstance(result, Failure):
        return result
    value = result.unwrap()
    if not isinstance(value, bool):
        return _error(
            EvaluationErrorCode.EXPECTED_CONDITION,
            "condition must evaluate to bool",
        )
    return Success(value)


def _evaluate_type(
    expression: Expression, context: EvaluationContext
) -> Result[StaticType, EvaluationError]:
    result = evaluate(expression, context)
    if isinstance(result, Failure):
        return result
    value = result.unwrap()
    if not isinstance(value, (NamedType, NeverType, UnionType, TypedDictShape)):
        return _error(
            EvaluationErrorCode.EXPECTED_TYPE,
            "expression must evaluate to a static type",
        )
    return Success(value)


def _is_assignable(source: StaticType, target: StaticType) -> bool:
    if isinstance(source, NeverType):
        return True
    if isinstance(source, UnionType):
        return all(_is_assignable(member, target) for member in source.members)
    if isinstance(target, UnionType):
        return any(_is_assignable(source, member) for member in target.members)
    if isinstance(source, NamedType) and isinstance(target, NamedType):
        return (
            source.name == target.name
            or target.name == "object"
            or target.name in source.bases
        )
    return source == target


def _error(code: EvaluationErrorCode, message: str) -> Failure[EvaluationError]:
    return Failure(EvaluationError(code, message))
