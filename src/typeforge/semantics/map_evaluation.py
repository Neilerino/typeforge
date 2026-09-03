"""Shared evaluation of Map members and structural type patterns."""

from collections.abc import Sequence
from dataclasses import replace
from functools import singledispatch
from typing import NamedTuple, Protocol

from typeforge.semantics.domain.assertions import expect_condition, expect_possible_type
from typeforge.semantics.domain.exceptions import UnsupportedExpressionSemanticError
from typeforge.semantics.domain.models import (
    CaptureValuePattern,
    DeferredMap,
    EvaluationContext,
    EvaluationValue,
    ExactTypePattern,
    Expression,
    FieldName,
    IndeterminateCondition,
    InputReference,
    MapExpression,
    ParameterizedTypePattern,
    ResolvedType,
    TypePattern,
    UnresolvedType,
    UnresolvedTypePattern,
    is_bool_expr,
    is_pattern_expr,
    is_unresolved_type,
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
    """A pattern decision and its optional `Value` binding."""

    matched: bool | None
    value_binding: ResolvedType[T] | None

    @classmethod
    def match(
        cls, value_binding: ResolvedType[T] | None = None
    ) -> _R_MatchTypePattern[T]:
        return cls(matched=True, value_binding=value_binding)

    @classmethod
    def mismatch(cls) -> _R_MatchTypePattern[T]:
        return cls(matched=False, value_binding=None)

    @classmethod
    def indeterminate(
        cls, value_binding: ResolvedType[T] | None = None
    ) -> _R_MatchTypePattern[T]:
        return cls(matched=None, value_binding=value_binding)


def evaluate_map[T](
    expression: MapExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
    *,
    fn: _ExpressionEvaluator[T],
) -> EvaluationValue[T]:
    if isinstance(expression.subject, InputReference) and context.input_type is None:
        return _defer_map(expression, type_system, context, fn=fn)

    subject = fn(expression.subject, type_system, context)
    members: tuple[EvaluationValue[T], ...]
    if isinstance(subject, UnresolvedType):
        members = (subject,)
    elif isinstance(subject, ResolvedType):
        native_members = type_system.union_members(subject.value).unwrap()
        members = tuple(ResolvedType(member) for member in native_members)
    else:
        members = (subject,)

    outputs = _evaluate_map_members(
        members,
        expression,
        type_system,
        context,
        fn=fn,
    )
    if len(outputs) == 1:
        return outputs[0]

    output_types = tuple(
        expect_possible_type(
            output,
            "Map outputs for a union subject must have possible output types",
        ).value
        for output in outputs
    )
    return ResolvedType(type_system.union(output_types).unwrap())


def _defer_map[T](
    expression: MapExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
    *,
    fn: _ExpressionEvaluator[T],
) -> DeferredMap[T]:
    output_types = tuple(
        expect_possible_type(
            fn(case.output, type_system, context),
            "deferred Map outputs must evaluate to types",
        ).value
        for case in expression.cases
    )
    if expression.default is not None:
        default_type = expect_possible_type(
            fn(expression.default, type_system, context),
            "deferred Map outputs must evaluate to types",
        )
        output_types = (*output_types, default_type.value)

    return DeferredMap(
        cases=expression.cases,
        default=expression.default,
        context=context,
        possible_output=ResolvedType(type_system.union(output_types).unwrap()),
    )


def _evaluate_map_members[T](
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
    for index, case in enumerate(expression.cases):
        output_context = context
        if is_bool_expr(case.test):
            condition = fn(case.test, type_system, context)
            matched = (
                None
                if isinstance(condition, IndeterminateCondition)
                else expect_condition(condition)
            )
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

        if matched is None:
            possible_output = expect_possible_type(
                fn(case.output, type_system, output_context),
                "indeterminate Map cases must have possible output types",
            )
            remaining_output = expect_possible_type(
                _evaluate_map_member(
                    subject,
                    replace(expression, cases=expression.cases[index + 1 :]),
                    type_system,
                    context,
                    fn=fn,
                ),
                "indeterminate Map cases must have possible output types",
            )
            return UnresolvedType(
                type_system.union(
                    (possible_output.value, remaining_output.value)
                ).unwrap()
            )
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
    equal = type_system.equal(subject.value, pattern.value).unwrap()
    if equal:
        return _R_MatchTypePattern[T].match()
    if isinstance(subject, UnresolvedType):
        return _R_MatchTypePattern[T].indeterminate()

    return _R_MatchTypePattern[T].mismatch()


@_match_type_pattern.register(UnresolvedTypePattern)
def _[T](
    pattern: UnresolvedTypePattern[T],
    subject: ResolvedType[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    if (
        isinstance(subject, UnresolvedType)
        and type_system.equal(subject.value, pattern.value).unwrap()
    ):
        return _R_MatchTypePattern[T].match()
    return _R_MatchTypePattern[T].indeterminate()


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
    inspected_shape = type_system.inspect(subject.value).unwrap()
    if inspected_shape is None:
        if isinstance(subject, UnresolvedType):
            return _R_MatchTypePattern[T].indeterminate()
        return _R_MatchTypePattern[T].mismatch()

    nested_values: tuple[ResolvedType[T], ...]
    if isinstance(subject, UnresolvedType) and subject.shape is not None:
        origin = subject.shape.origin
        nested_values = subject.shape.arguments
    else:
        origin = inspected_shape.origin
        nested_values = tuple(
            UnresolvedType[T](argument)
            if isinstance(subject, UnresolvedType)
            else ResolvedType[T](argument)
            for argument in inspected_shape.arguments
        )

    if (
        len(nested_values) != len(pattern.arguments)
        or not type_system.equal(origin, pattern.origin).unwrap()
    ):
        return _R_MatchTypePattern[T].mismatch()

    current_binding: ResolvedType[T] | None = None
    has_indeterminate = False
    for nested_pattern, nested_value in zip(
        pattern.arguments,
        nested_values,
        strict=True,
    ):
        nested_result: _R_MatchTypePattern[T] = _match_type_pattern(
            nested_pattern,
            nested_value,
            type_system,
        )
        matched = nested_result.matched
        nested_binding: ResolvedType[T] | None = nested_result.value_binding
        if matched is False:
            return _R_MatchTypePattern[T].mismatch()
        if matched is None:
            has_indeterminate = True

        # One `Value` binding is shared by the whole pattern. The first nested
        # binding establishes it; every later binding must resolve to the same type.
        if nested_binding is None:
            continue

        if current_binding is None:
            current_binding = nested_binding
            continue

        bindings_equal = type_system.equal(
            current_binding.value,
            nested_binding.value,
        ).unwrap()
        if bindings_equal:
            continue
        if is_unresolved_type(current_binding) or is_unresolved_type(nested_binding):
            has_indeterminate = True
            if is_unresolved_type(current_binding) and not is_unresolved_type(
                nested_binding
            ):
                current_binding = nested_binding
            continue
        return _R_MatchTypePattern[T].mismatch()

    if has_indeterminate:
        return _R_MatchTypePattern[T].indeterminate(current_binding)
    return _R_MatchTypePattern[T].match(current_binding)


def _map_values_are_equal[T](
    left: EvaluationValue[T],
    right: EvaluationValue[T],
    type_system: TypeSystem[T],
) -> bool | None:
    if isinstance(left, ResolvedType) and isinstance(right, ResolvedType):
        equal = type_system.equal(left.value, right.value).unwrap()
        if equal:
            return True
        if is_unresolved_type(left) or is_unresolved_type(right):
            return None
        return False

    if isinstance(left, FieldName) and isinstance(right, FieldName):
        return left == right

    return False


__all__ = ("evaluate_map",)
