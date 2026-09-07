"""Shared evaluation of Map members and structural type patterns."""

from collections.abc import Sequence
from dataclasses import replace
from functools import singledispatch
from typing import NamedTuple, Protocol, assert_never

from typeforge.semantics.domain.assertions import (
    expect_condition,
    expect_possible_type,
)
from typeforge.semantics.domain.exceptions import UnsupportedExpressionSemanticError
from typeforge.semantics.domain.models import (
    CaptureValuePattern,
    Condition,
    DeferredMap,
    EvaluationContext,
    EvaluationValue,
    ExactTypePattern,
    Expression,
    FieldName,
    IndeterminateCondition,
    IndeterminateType,
    InputReference,
    MapExpression,
    ParameterizedTypePattern,
    ResolvedType,
    TypePattern,
    TypeValue,
    TypeValueReference,
    UnresolvedType,
    is_bool_expr,
    is_pattern_expr,
)
from typeforge.semantics.protocols import TypeSystem
from typeforge.semantics.type_evaluation import (
    consensus,
    equal_types,
    indeterminate_type,
    inspect_type,
    is_symbol,
    merge_captures,
    union_members,
    union_type,
)


class _ExpressionEvaluator[T](Protocol):
    def __call__(
        self,
        expression: Expression[T],
        type_system: TypeSystem[T],
        context: EvaluationContext[T],
    ) -> EvaluationValue[T]: ...


class _R_MatchTypePattern[T](NamedTuple):
    """A mismatch, a match without `Value`, or a match with a `Value` binding."""

    matched: Condition
    value_binding: TypeValue[T] | None

    @classmethod
    def match(cls, value_binding: TypeValue[T] | None = None) -> _R_MatchTypePattern[T]:
        return cls(matched=True, value_binding=value_binding)

    @classmethod
    def mismatch(cls) -> _R_MatchTypePattern[T]:
        return cls(matched=False, value_binding=None)


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
    if isinstance(subject, ResolvedType | UnresolvedType):
        members = union_members(subject, type_system)
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

    return union_type(
        outputs, type_system, "Map outputs for a union subject must evaluate to types"
    )


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
            matched = expect_condition(fn(case.test, type_system, context))

        elif is_pattern_expr(case.test):
            if isinstance(subject, ResolvedType | UnresolvedType | IndeterminateType):
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

        if matched is True:
            return fn(case.output, type_system, output_context)

        if isinstance(matched, IndeterminateCondition):
            selected = fn(case.output, type_system, output_context)
            expect_possible_type(
                selected, "indeterminate Map outputs must evaluate to types"
            )
            remaining = _evaluate_map_member(
                subject,
                replace(expression, cases=expression.cases[index + 1 :]),
                type_system,
                context,
                fn=fn,
            )
            return indeterminate_type((selected, remaining), type_system)

    if expression.default is not None:
        return fn(expression.default, type_system, context)

    return ResolvedType(type_system.union(()).unwrap())


@singledispatch
def _match_type_pattern[T](
    pattern: TypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    raise UnsupportedExpressionSemanticError(
        f"unsupported type pattern {type(pattern).__name__}"
    )


@_match_type_pattern.register(ExactTypePattern)
def _[T](
    pattern: ExactTypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    return _R_MatchTypePattern(
        equal_types(subject, ResolvedType(pattern.value), type_system), None
    )


@_match_type_pattern.register(CaptureValuePattern)
def _[T](
    pattern: CaptureValuePattern,
    subject: TypeValue[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    return _R_MatchTypePattern[T].match(subject)


@_match_type_pattern.register(TypeValueReference)
def _[T](
    pattern: TypeValueReference[T], subject: TypeValue[T], type_system: TypeSystem[T]
) -> _R_MatchTypePattern[T]:
    return _R_MatchTypePattern(equal_types(subject, pattern.value, type_system), None)


@_match_type_pattern.register(ParameterizedTypePattern)
def _[T](
    pattern: ParameterizedTypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    if isinstance(subject, IndeterminateType):
        matches = tuple(
            _match_type_pattern(pattern, alternative, type_system)
            for alternative in subject.alternatives
        )
        bindings = tuple(
            match.value_binding
            for match in matches
            if match.matched is not False and match.value_binding is not None
        )
        binding = (
            indeterminate_type(bindings, type_system)
            if len(bindings) > 1
            else (bindings[0] if bindings else None)
        )
        return _R_MatchTypePattern(
            consensus(match.matched for match in matches), binding
        )

    if is_symbol(subject):
        if _has_capture(pattern):
            raise UnsupportedExpressionSemanticError(
                "cannot capture type arguments from an unresolved type parameter"
            )

        return _R_MatchTypePattern(IndeterminateCondition(), None)

    shape = inspect_type(subject, type_system)
    if shape is None or len(shape.arguments) != len(pattern.arguments):
        return _R_MatchTypePattern[T].mismatch()

    origin_match = equal_types(shape.origin, ResolvedType(pattern.origin), type_system)
    if origin_match is False:
        return _R_MatchTypePattern[T].mismatch()

    uncertain = isinstance(origin_match, IndeterminateCondition)
    current_binding: TypeValue[T] | None = None
    for nested_pattern, nested_subject in zip(
        pattern.arguments, shape.arguments, strict=True
    ):
        matched, nested_binding = _match_type_pattern(
            nested_pattern, nested_subject, type_system
        )
        if matched is False:
            return _R_MatchTypePattern[T].mismatch()

        uncertain |= isinstance(matched, IndeterminateCondition)
        if nested_binding is None:
            continue

        if current_binding is None:
            current_binding = nested_binding
            continue

        matched, current_binding = merge_captures(
            current_binding, nested_binding, type_system
        )
        if matched is False:
            return _R_MatchTypePattern[T].mismatch()

        uncertain |= isinstance(matched, IndeterminateCondition)

    return _R_MatchTypePattern(
        IndeterminateCondition() if uncertain else True, current_binding
    )


def _map_values_are_equal[T](
    left: EvaluationValue[T],
    right: EvaluationValue[T],
    type_system: TypeSystem[T],
) -> Condition:
    if isinstance(
        left, ResolvedType | UnresolvedType | IndeterminateType
    ) and isinstance(right, ResolvedType | UnresolvedType | IndeterminateType):
        return equal_types(left, right, type_system)

    if isinstance(left, FieldName) and isinstance(right, FieldName):
        return left == right

    return False


def _has_capture[T](pattern: TypePattern[T]) -> bool:
    match pattern:
        case CaptureValuePattern():
            return True
        case ParameterizedTypePattern(arguments=arguments):
            return any(_has_capture(argument) for argument in arguments)
        case ExactTypePattern() | TypeValueReference():
            return False
        case _ as unreachable:
            assert_never(unreachable)


__all__ = ("evaluate_map",)
