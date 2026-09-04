"""Assertions for values produced during semantic evaluation."""

from typeforge.semantics.domain.exceptions import (
    ExpectedConditionSemanticError,
    ExpectedFieldNameSemanticError,
    ExpectedFieldSemanticError,
    ExpectedTypeSemanticError,
)
from typeforge.semantics.domain.models import (
    EvaluationValue,
    FieldName,
    RecordField,
    ResolvedType,
)


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
) -> bool:
    if isinstance(value, bool):
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
