"""Shared matching primitives; ordered selection belongs to Evaluator."""

from functools import singledispatch
from typing import NamedTuple, assert_never

from typeforge.semantics.domain.exceptions import UnsupportedExpressionSemanticError
from typeforge.semantics.domain.models import (
    CaptureValuePattern,
    Condition,
    EvaluationValue,
    ExactTypePattern,
    FieldName,
    IndeterminateCondition,
    IndeterminateType,
    ParameterizedTypePattern,
    ResolvedType,
    TypePattern,
    TypeValue,
    TypeValueReference,
    UnresolvedType,
)
from typeforge.semantics.protocols import TypeSystem
from typeforge.semantics.type_evaluation import (
    assignable_types,
    consensus,
    equal_types,
    indeterminate_type,
    inspect_type,
    is_symbol,
    merge_captures,
)


class _R_MatchTypePattern[T](NamedTuple):
    """A mismatch, a match without `Value`, or a match with a `Value` binding."""

    matched: Condition
    value_binding: TypeValue[T] | None = None

    @classmethod
    def match(cls, value_binding: TypeValue[T] | None = None) -> _R_MatchTypePattern[T]:
        return cls(matched=True, value_binding=value_binding)

    @classmethod
    def mismatch(cls) -> _R_MatchTypePattern[T]:
        return cls(matched=False, value_binding=None)


@singledispatch
def match_type_pattern[T](
    pattern: TypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    raise UnsupportedExpressionSemanticError(
        f"unsupported type pattern {type(pattern).__name__}"
    )


@match_type_pattern.register(ExactTypePattern)
def _[T](
    pattern: ExactTypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    return _R_MatchTypePattern(
        equal_types(
            left=subject, right=ResolvedType(pattern.value), type_system=type_system
        )
    )


@match_type_pattern.register(CaptureValuePattern)
def _[T](
    pattern: CaptureValuePattern,
    subject: TypeValue[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    return _R_MatchTypePattern[T].match(subject)


@match_type_pattern.register(TypeValueReference)
def _[T](
    pattern: TypeValueReference[T], subject: TypeValue[T], type_system: TypeSystem[T]
) -> _R_MatchTypePattern[T]:
    return _R_MatchTypePattern(equal_types(subject, pattern.value, type_system))


@match_type_pattern.register(ParameterizedTypePattern)
def _[T](
    pattern: ParameterizedTypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
) -> _R_MatchTypePattern[T]:
    if isinstance(subject, IndeterminateType):
        matches = tuple(
            match_type_pattern(pattern, alternative, type_system)
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
        matched, nested_binding = match_type_pattern(
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


def map_values_match[T](
    left: EvaluationValue[T],
    right: EvaluationValue[T],
    type_system: TypeSystem[T],
) -> Condition:
    if isinstance(
        left, ResolvedType | UnresolvedType | IndeterminateType
    ) and isinstance(right, ResolvedType | UnresolvedType | IndeterminateType):
        return assignable_types(left, right, type_system)

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


__all__ = ("map_values_match", "match_type_pattern")
