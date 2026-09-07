"""Assertions for values produced during semantic evaluation."""

from typeforge.semantics.domain.exceptions import (
    ExpectedConditionSemanticError,
    ExpectedFieldNameSemanticError,
    ExpectedFieldSemanticError,
    ExpectedTypeSemanticError,
)
from typeforge.semantics.domain.models import (
    Condition,
    DeferredMap,
    EvaluationValue,
    FieldName,
    IndeterminateCondition,
    IndeterminateType,
    RecordField,
    ResolvedType,
    TypeValue,
    UnresolvedType,
)


def expect_possible_type[T](
    value: EvaluationValue[T],
    message: str,
) -> ResolvedType[T]:
    """Obtain a static output bound without treating deferred selection as resolved."""
    if isinstance(value, DeferredMap | IndeterminateType):
        return value.possible_output

    if isinstance(value, UnresolvedType):
        return ResolvedType(value.value)

    return expect_type(value, message)


def expect_type[T](
    value: EvaluationValue[T],
    message: str = "type must evaluate to ResolvedType",
) -> ResolvedType[T]:
    if isinstance(value, ResolvedType):
        return value

    raise ExpectedTypeSemanticError(message)


def expect_condition[T](
    value: EvaluationValue[T],
    message: str = "condition must evaluate to bool",
) -> Condition:
    if isinstance(value, bool | IndeterminateCondition):
        return value

    raise ExpectedConditionSemanticError(message)


def expect_field_name[T](
    value: EvaluationValue[T],
    message: str = "field name must evaluate to FieldName",
) -> FieldName:
    if isinstance(value, FieldName):
        return value

    raise ExpectedFieldNameSemanticError(message)


def expect_field[T](
    value: EvaluationValue[T],
    message: str = "field must evaluate to RecordField",
) -> RecordField[T]:
    if isinstance(value, RecordField):
        return value

    raise ExpectedFieldSemanticError(message)


def expect_type_value[T](value: EvaluationValue[T], message: str) -> TypeValue[T]:
    if isinstance(value, ResolvedType | UnresolvedType | IndeterminateType):
        return value

    raise ExpectedTypeSemanticError(message)
