"""Shared matching primitives; ordered selection belongs to Evaluator."""

from functools import singledispatch
from typing import NamedTuple, assert_never

from typeforge.semantics.domain.exceptions import (
    UnresolvedCaptureSemanticError,
    UnsupportedExpressionSemanticError,
)
from typeforge.semantics.domain.models import (
    CaptureBindings,
    CaptureReference,
    CaptureValuePattern,
    Condition,
    EvaluationValue,
    ExactTypePattern,
    FieldName,
    IndeterminateCondition,
    IndeterminateType,
    ParameterizedTypePattern,
    ParameterizedTypeShape,
    ResolvedType,
    TypePattern,
    TypeSymbol,
    TypeValue,
    TypeValueReference,
    UnresolvedType,
)
from typeforge.semantics.protocols import TypeSystem
from typeforge.semantics.type_evaluation import (
    assignable_types,
    build_type,
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
    captures: CaptureBindings[T] = ()

    @classmethod
    def match(
        cls,
        value_binding: TypeValue[T] | None = None,
        captures: CaptureBindings[T] = (),
    ) -> _R_MatchTypePattern[T]:
        return cls(matched=True, value_binding=value_binding, captures=captures)

    @classmethod
    def mismatch(cls) -> _R_MatchTypePattern[T]:
        return cls(matched=False, value_binding=None)


def match_map_pattern[T](
    pattern: TypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _R_MatchTypePattern[T]:
    """Resolved fixed selectors use compatibility; captures retain structural rules."""
    # Partially known shapes retain structural proofs and their provenance;
    # native variance operations require complete backend types.
    if isinstance(subject, ResolvedType) and isinstance(
        pattern, ParameterizedTypePattern
    ):
        target = _fixed_pattern_type(pattern, type_system)
        if target is not None:
            return _R_MatchTypePattern(
                assignable_types(subject, target, type_system), captures=captures
            )

    return match_type_pattern(pattern, subject, type_system, captures)


def _fixed_pattern_type[T](
    pattern: TypePattern[T], type_system: TypeSystem[T]
) -> TypeValue[T] | None:
    match pattern:
        case ExactTypePattern(value=value):
            return ResolvedType(value)
        case TypeValueReference(value=value):
            return value if isinstance(value, ResolvedType) else None
        case CaptureValuePattern() | CaptureReference():
            return None
        case ParameterizedTypePattern(origin=origin, arguments=arguments):
            values: list[TypeValue[T]] = []
            for argument in arguments:
                argument_type = _fixed_pattern_type(argument, type_system)
                if argument_type is None:
                    return None

                values.append(argument_type)

            return build_type(
                ParameterizedTypeShape(ResolvedType(origin), tuple(values)), type_system
            )
        case _ as unreachable:
            assert_never(unreachable)


@singledispatch
def match_type_pattern[T](
    pattern: TypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _R_MatchTypePattern[T]:
    raise UnsupportedExpressionSemanticError(
        f"unsupported type pattern {type(pattern).__name__}"
    )


@match_type_pattern.register(ExactTypePattern)
def _[T](
    pattern: ExactTypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _R_MatchTypePattern[T]:
    return _R_MatchTypePattern(
        equal_types(
            left=subject, right=ResolvedType(pattern.value), type_system=type_system
        ),
        captures=captures,
    )


@match_type_pattern.register(CaptureValuePattern)
def _[T](
    pattern: CaptureValuePattern,
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _R_MatchTypePattern[T]:
    return _R_MatchTypePattern[T].match(subject, captures)


@match_type_pattern.register(CaptureReference)
def _[T](
    pattern: CaptureReference,
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _R_MatchTypePattern[T]:
    bound = dict(captures).get(pattern.symbol)
    if bound is not None:
        matched, binding = merge_captures(bound, subject, type_system)
        if matched is False:
            return _R_MatchTypePattern[T].mismatch()

        return _R_MatchTypePattern(
            matched,
            captures=tuple(
                (symbol, binding if symbol == pattern.symbol else value)
                for symbol, value in captures
            ),
        )

    return _R_MatchTypePattern[T].match(captures=(*captures, (pattern.symbol, subject)))


@match_type_pattern.register(TypeValueReference)
def _[T](
    pattern: TypeValueReference[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _R_MatchTypePattern[T]:
    return _R_MatchTypePattern(
        equal_types(subject, pattern.value, type_system), captures=captures
    )


@match_type_pattern.register(ParameterizedTypePattern)
def _[T](
    pattern: ParameterizedTypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _R_MatchTypePattern[T]:
    if isinstance(subject, IndeterminateType):
        matches = tuple(
            match_type_pattern(pattern, alternative, type_system, captures)
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
            consensus(match.matched for match in matches),
            binding,
            _possible_captures(matches, type_system),
        )

    if is_symbol(subject):
        if _has_named_capture(pattern):
            raise UnresolvedCaptureSemanticError(
                "cannot capture type arguments from an unresolved type parameter"
            )

        if _has_capture(pattern):
            raise UnsupportedExpressionSemanticError(
                "cannot capture type arguments from an unresolved type parameter"
            )

        return _R_MatchTypePattern(IndeterminateCondition(), captures=captures)

    shape = inspect_type(subject, type_system)
    if shape is None or len(shape.arguments) != len(pattern.arguments):
        return _R_MatchTypePattern[T].mismatch()

    origin_match = equal_types(shape.origin, ResolvedType(pattern.origin), type_system)
    if origin_match is False:
        return _R_MatchTypePattern[T].mismatch()

    uncertain = isinstance(origin_match, IndeterminateCondition)
    current_binding: TypeValue[T] | None = None
    current_captures = captures
    for nested_pattern, nested_subject in zip(
        pattern.arguments, shape.arguments, strict=True
    ):
        nested_match = match_type_pattern(
            nested_pattern, nested_subject, type_system, current_captures
        )
        matched = nested_match.matched
        nested_binding = nested_match.value_binding
        if matched is False:
            return _R_MatchTypePattern[T].mismatch()

        uncertain |= isinstance(matched, IndeterminateCondition)
        current_captures = nested_match.captures
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
        IndeterminateCondition() if uncertain else True,
        current_binding,
        current_captures,
    )


def _possible_captures[T](
    matches: tuple[_R_MatchTypePattern[T], ...], type_system: TypeSystem[T]
) -> CaptureBindings[T]:
    possible = [dict(match.captures) for match in matches if match.matched is not False]
    if not possible:
        return ()

    bindings: list[tuple[TypeSymbol, TypeValue[T]]] = []
    for symbol in possible[0]:
        if not all(symbol in alternative for alternative in possible):
            continue

        values = tuple(alternative[symbol] for alternative in possible)
        value = (
            values[0] if len(values) == 1 else indeterminate_type(values, type_system)
        )
        bindings.append((symbol, value))

    return tuple(bindings)


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
        case CaptureValuePattern() | CaptureReference():
            return True
        case ParameterizedTypePattern(arguments=arguments):
            return any(_has_capture(argument) for argument in arguments)
        case ExactTypePattern() | TypeValueReference():
            return False
        case _ as unreachable:
            assert_never(unreachable)


def _has_named_capture[T](pattern: TypePattern[T]) -> bool:
    match pattern:
        case CaptureReference():
            return True
        case ParameterizedTypePattern(arguments=arguments):
            return any(_has_named_capture(argument) for argument in arguments)
        case _:
            return False


__all__ = ("map_values_match", "match_type_pattern")
