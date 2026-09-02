"""Shared evaluation of Map members and structural type patterns."""

from collections.abc import Sequence
from dataclasses import replace
from functools import singledispatch
from typing import NamedTuple, Protocol

from typeforge.semantics.domain.assertions import expect_condition
from typeforge.semantics.domain.exceptions import UnsupportedExpressionSemanticError
from typeforge.semantics.domain.models import (
    CaptureValuePattern,
    EvaluationContext,
    EvaluationValue,
    ExactTypePattern,
    Expression,
    FieldName,
    MapExpression,
    ParameterizedTypePattern,
    ResolvedType,
    TypePattern,
    is_bool_expr,
    is_pattern_expr,
)
from typeforge.semantics.protocols import TypeSystem


class _ExpressionEvaluator[T](Protocol):
    def __call__(
        self,
        expression: Expression[T],
        type_system: TypeSystem[T],
        context: EvaluationContext[T],
    ) -> EvaluationValue[T]: ...


class _R_MatchTypePattern[T](NamedTuple):
    """A mismatch, a match without `Value`, or a match with a `Value` binding."""

    matched: bool
    value_binding: ResolvedType[T] | None

    @classmethod
    def match(
        cls, value_binding: ResolvedType[T] | None = None
    ) -> _R_MatchTypePattern[T]:
        return cls(matched=True, value_binding=value_binding)

    @classmethod
    def mismatch(cls) -> _R_MatchTypePattern[T]:
        return cls(matched=False, value_binding=None)


def evaluate_map_members[T](
    members: Sequence[EvaluationValue[T]],
    expression: MapExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
    *,
    fn: _ExpressionEvaluator[T],
) -> tuple[EvaluationValue[T], ...]:
    return tuple(
        _evaluate_map_member(
            member,
            expression,
            type_system,
            context,
            fn=fn,
        )
        for member in members
    )


def _evaluate_map_member[T](
    subject: EvaluationValue[T],
    expression: MapExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
    *,
    fn: _ExpressionEvaluator[T],
) -> EvaluationValue[T]:
    for case in expression.cases:
        output_context = context
        if is_bool_expr(case.test):
            matched = expect_condition(fn(case.test, type_system, context))

        elif is_pattern_expr(case.test):
            if isinstance(subject, ResolvedType):
                matched, value_binding = _match_type_pattern(
                    case.test,
                    subject,
                    type_system,
                )
                output_context = replace(context, capture=value_binding)
            else:
                matched = False

        else:
            test = fn(case.test, type_system, context)
            matched = _map_values_are_equal(subject, test, type_system)
        if matched:
            return fn(case.output, type_system, output_context)

    if expression.default is not None:
        return fn(expression.default, type_system, context)

    return ResolvedType(type_system.union(()).unwrap())


@singledispatch
def _match_type_pattern[T](
    pattern: TypePattern[T],
    subject: ResolvedType[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    raise UnsupportedExpressionSemanticError(
        f"unsupported type pattern {type(pattern).__name__}"
    )


@_match_type_pattern.register(ExactTypePattern)
def _[T](
    pattern: ExactTypePattern[T],
    subject: ResolvedType[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    if type_system.equal(subject.value, pattern.value).unwrap():
        return _R_MatchTypePattern[T].match()

    return _R_MatchTypePattern[T].mismatch()


@_match_type_pattern.register(CaptureValuePattern)
def _[T](
    pattern: CaptureValuePattern,
    subject: ResolvedType[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    return _R_MatchTypePattern[T].match(subject)


@_match_type_pattern.register(ParameterizedTypePattern)
def _[T](
    pattern: ParameterizedTypePattern[T],
    subject: ResolvedType[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    if (
        (shape := type_system.inspect(subject.value).unwrap()) is None
        or len(shape.arguments) != len(pattern.arguments)
        or not type_system.equal(shape.origin, pattern.origin).unwrap()
    ):
        return _R_MatchTypePattern[T].mismatch()

    current_binding: ResolvedType[T] | None = None
    for nested_pattern, nested_subject in zip(
        pattern.arguments,
        shape.arguments,
        strict=True,
    ):
        matched, nested_binding = _match_type_pattern(
            nested_pattern,
            ResolvedType(nested_subject),
            type_system,
        )
        if not matched:
            return _R_MatchTypePattern[T].mismatch()

        # One `Value` binding is shared by the whole pattern. The first nested
        # binding establishes it; every later binding must resolve to the same type.
        if nested_binding is None:
            continue

        if current_binding is None:
            current_binding = nested_binding
            continue

        if not type_system.equal(
            current_binding.value,
            nested_binding.value,
        ).unwrap():
            return _R_MatchTypePattern[T].mismatch()

    return _R_MatchTypePattern[T].match(current_binding)


def _map_values_are_equal[T](
    left: EvaluationValue[T],
    right: EvaluationValue[T],
    type_system: TypeSystem[T],
) -> bool:
    if isinstance(left, ResolvedType) and isinstance(right, ResolvedType):
        return type_system.equal(left.value, right.value).unwrap()

    if isinstance(left, FieldName) and isinstance(right, FieldName):
        return left == right

    return False


__all__ = ("evaluate_map_members",)
