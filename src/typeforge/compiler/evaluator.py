from dataclasses import dataclass
from enum import StrEnum
from functools import singledispatch
from typing import ClassVar, TypeIs

from returns.result import safe

from typeforge.compiler.records import (
    NEVER,
    NamedType,
    NeverType,
    StaticType,
    TypedDictField,
    TypedDictShape,
    UnionType,
    is_static,
    union_of,
)
from typeforge.utils.error_handling import ok


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
class Case:
    test: Expression
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
    UNSUPPORTED_EXPRESSION = "unsupported_expression"
    DEFAULT = "evaluator_base_error_inherit_me"


@dataclass(frozen=True)
class EvaluationError(Exception):
    message: str
    code: ClassVar[EvaluationErrorCode] = EvaluationErrorCode.DEFAULT


class UnboundKeyError(EvaluationError):
    code = EvaluationErrorCode.UNBOUND_KEY


class UnboundValueError(EvaluationError):
    code = EvaluationErrorCode.UNBOUND_VALUE


class ExpectedTypeError(EvaluationError):
    code = EvaluationErrorCode.EXPECTED_TYPE


class ExpectedConditionError(EvaluationError):
    code = EvaluationErrorCode.EXPECTED_CONDITION


class ExpectedFieldNameError(EvaluationError):
    code = EvaluationErrorCode.EXPECTED_FIELD_NAME


class ExpectedFieldError(EvaluationError):
    code = EvaluationErrorCode.EXPECTED_FIELD


class ExpectedTypedDictError(EvaluationError):
    code = EvaluationErrorCode.EXPECTED_TYPED_DICT


class UnsupportedExpressionError(EvaluationError):
    code = EvaluationErrorCode.UNSUPPORTED_EXPRESSION


@singledispatch
@safe(exceptions=(EvaluationError,))
def evaluate(
    expression: Expression, context: EvaluationContext = EMPTY_CONTEXT
) -> EvaluationValue:
    raise UnsupportedExpressionError(
        f"unsupported expression {type(expression).__name__}"
    )


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(expression: Drop, context: EvaluationContext = EMPTY_CONTEXT) -> EvaluationValue:
    return DroppedField()


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(
    expression: NamedType | NeverType | UnionType | TypedDictShape | FieldName,
    context: EvaluationContext = EMPTY_CONTEXT,
) -> EvaluationValue:
    return expression


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(expression: Key, context: EvaluationContext = EMPTY_CONTEXT) -> EvaluationValue:
    if context.key is None:
        raise UnboundKeyError("Key requires MapFields")
    return FieldName(context.key)


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(expression: Value, context: EvaluationContext = EMPTY_CONTEXT) -> EvaluationValue:
    if context.value is None:
        raise UnboundValueError("Value requires MapFields")
    return context.value


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(expression: Equal, context: EvaluationContext = EMPTY_CONTEXT) -> EvaluationValue:
    return ok(evaluate(expression.left, context)) == ok(
        evaluate(expression.right, context)
    )


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(
    expression: Assignable, context: EvaluationContext = EMPTY_CONTEXT
) -> EvaluationValue:
    source_type = ok(evaluate(expression.source, context))
    target_type = ok(evaluate(expression.target, context))

    if not is_static(source_type) or not is_static(target_type):
        raise ExpectedTypeError("Assignable requires static types")

    return _is_assignable(source_type, target_type)


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(expression: All | Any, context: EvaluationContext = EMPTY_CONTEXT) -> bool:
    for condition in expression.conditions:
        match expression, ok(evaluate(condition, context)):
            case All(), False:
                return False
            case Any(), True:
                return True
            case _, bool():
                continue
            case _:
                raise ExpectedConditionError("condition must evaluate to bool")

    return isinstance(expression, All)


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(expression: Not, context: EvaluationContext = EMPTY_CONTEXT) -> bool:
    result = ok(evaluate(expression.condition, context))
    if not isinstance(result, bool):
        raise ExpectedConditionError("condition must evaluate to bool")

    return not result


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(expression: Map, context: EvaluationContext = EMPTY_CONTEXT) -> EvaluationValue:
    subject = ok(evaluate(expression.subject, context))
    members: tuple[EvaluationValue, ...] = (
        subject.members if isinstance(subject, UnionType) else (subject,)
    )
    outputs: list[EvaluationValue] = []
    for member in members:
        output_expression = expression.default
        for case in expression.cases:
            if _is_condition(case.test):
                matched = ok(evaluate(case.test, context))
                if not isinstance(matched, bool):
                    raise ExpectedConditionError("condition must evaluate to bool")
            else:
                matched = member == ok(evaluate(case.test, context))
            if matched:
                output_expression = case.output_type
                break
        outputs.append(ok(evaluate(output_expression, context)))

    if len(outputs) == 1:
        return outputs[0]
    if all(is_static(output) for output in outputs):
        return union_of(*(output for output in outputs if is_static(output)))
    raise ExpectedTypeError("Map outputs for a union subject must be static types")


def _is_condition(
    expression: Expression,
) -> TypeIs[Equal | Assignable | All | Any | Not]:
    return isinstance(expression, Equal | Assignable | All | Any | Not)


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(
    expression: Field | OptionalField | ReadonlyField,
    context: EvaluationContext = EMPTY_CONTEXT,
) -> TypedDictField:
    field_name = ok(evaluate(expression.name, context))
    if not isinstance(field_name, FieldName):
        raise ExpectedFieldNameError("field name must evaluate to FieldName")

    if is_static(value := ok(evaluate(expression.value, context))):
        return TypedDictField(
            field_name.value,
            value,
            required=not isinstance(expression, OptionalField),
            readonly=isinstance(expression, ReadonlyField),
        )

    raise ExpectedTypeError("field value must evaluate to a static type")


@evaluate.register
@safe(exceptions=(EvaluationError,))
def _(
    expression: MapFields, context: EvaluationContext = EMPTY_CONTEXT
) -> TypedDictShape:
    record = ok(evaluate(expression.record, context))
    if not isinstance(record, TypedDictShape):
        raise ExpectedTypedDictError(
            "MapFields record must evaluate to a TypedDictShape"
        )

    fields: list[TypedDictField] = []
    for source_field in record.fields:
        eval_context = EvaluationContext(source_field.name, source_field.value)

        match f := ok(evaluate(expression.transform, eval_context)):
            case TypedDictField():
                fields.append(f)
            case DroppedField():
                continue
            case _:
                raise ExpectedFieldError(
                    "MapFields transform must evaluate to a field or Drop"
                )

    return TypedDictShape(
        expression.output_name or record.name,
        tuple(fields),
    )


def _is_assignable(source: StaticType, target: StaticType) -> bool:
    match source, target:
        case NeverType(), _:
            return True

        case UnionType(), _:
            return all(_is_assignable(member, target) for member in source.members)

        case _, UnionType():
            return any(_is_assignable(source, member) for member in target.members)

        case NamedType(), NamedType():
            return (
                source.name == target.name
                or target.name == "object"
                or target.name in source.bases
            )

        case _:
            return source == target
