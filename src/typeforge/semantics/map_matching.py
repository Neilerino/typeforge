"""Shared matching primitives; ordered selection belongs to Evaluator."""

from functools import singledispatch
from typing import NamedTuple, assert_never

from typeforge.semantics.domain.assertions import expect_possible_type
from typeforge.semantics.domain.exceptions import (
    UnresolvedCaptureSemanticError,
    UnsupportedExpressionSemanticError,
)
from typeforge.semantics.domain.generics import GenericFamily, GenericType
from typeforge.semantics.domain.models import (
    CaptureBindings,
    CaptureReference,
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
from typeforge.semantics.generic_compatibility import sequence_elements
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
    union_type,
)


class _PatternMatch[T](NamedTuple):
    """A condition and its isolated named bindings."""

    matched: Condition
    captures: CaptureBindings[T] = ()

    @classmethod
    def match(
        cls,
        captures: CaptureBindings[T] = (),
    ) -> _PatternMatch[T]:
        return cls(matched=True, captures=captures)

    @classmethod
    def mismatch(cls) -> _PatternMatch[T]:
        return cls(matched=False)


def match_map_pattern[T](
    pattern: TypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _PatternMatch[T]:
    """Resolved fixed selectors use compatibility; captures retain structural rules."""
    # Partially known shapes retain structural proofs and their provenance;
    # native variance operations require complete backend types.
    if isinstance(subject, ResolvedType) and isinstance(
        pattern, ParameterizedTypePattern
    ):
        target = _fixed_pattern_type(pattern, type_system)
        if target is not None:
            return _PatternMatch(
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
        case CaptureReference():
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
) -> _PatternMatch[T]:
    raise UnsupportedExpressionSemanticError(
        f"unsupported type pattern {type(pattern).__name__}"
    )


@match_type_pattern.register(ExactTypePattern)
def _[T](
    pattern: ExactTypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _PatternMatch[T]:
    return _PatternMatch(
        equal_types(
            left=subject, right=ResolvedType(pattern.value), type_system=type_system
        ),
        captures=captures,
    )


@match_type_pattern.register(CaptureReference)
def _[T](
    pattern: CaptureReference,
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _PatternMatch[T]:
    bound = dict(captures).get(pattern.symbol)
    if bound is not None:
        matched, binding = merge_captures(bound, subject, type_system)
        if matched is False:
            return _PatternMatch[T].mismatch()

        return _PatternMatch(
            matched,
            captures=tuple(
                (symbol, binding if symbol == pattern.symbol else value)
                for symbol, value in captures
            ),
        )

    return _PatternMatch[T].match(captures=(*captures, (pattern.symbol, subject)))


@match_type_pattern.register(TypeValueReference)
def _[T](
    pattern: TypeValueReference[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _PatternMatch[T]:
    return _PatternMatch(
        equal_types(subject, pattern.value, type_system), captures=captures
    )


@match_type_pattern.register(ParameterizedTypePattern)
def _[T](
    pattern: ParameterizedTypePattern[T],
    subject: TypeValue[T],
    type_system: TypeSystem[T],
    captures: CaptureBindings[T] = (),
) -> _PatternMatch[T]:
    if isinstance(subject, IndeterminateType):
        matches = tuple(
            match_type_pattern(pattern, alternative, type_system, captures)
            for alternative in subject.alternatives
        )
        return _PatternMatch(
            consensus(match.matched for match in matches),
            _possible_captures(matches, type_system),
        )

    if is_symbol(subject):
        bound_symbols = frozenset(symbol for symbol, _ in captures)
        if _has_unbound_capture(pattern, bound_symbols):
            raise UnresolvedCaptureSemanticError(
                "cannot capture type arguments from an unresolved type parameter"
            )

        return _PatternMatch(IndeterminateCondition(), captures=captures)

    shape = inspect_type(subject, type_system)
    if shape is None:
        return _PatternMatch[T].mismatch()

    origin_match = equal_types(shape.origin, ResolvedType(pattern.origin), type_system)
    arguments = shape.arguments
    if origin_match is False:
        projected = _project_interface(pattern, shape, type_system)
        if projected is None:
            return _PatternMatch[T].mismatch()

        arguments = projected
        origin_match = True

    if len(arguments) != len(pattern.arguments):
        return _PatternMatch[T].mismatch()

    uncertain = isinstance(origin_match, IndeterminateCondition)
    current_captures = captures
    for nested_pattern, nested_subject in zip(
        pattern.arguments, arguments, strict=True
    ):
        nested_match = match_type_pattern(
            nested_pattern, nested_subject, type_system, current_captures
        )
        matched = nested_match.matched
        if matched is False:
            return _PatternMatch[T].mismatch()

        uncertain |= isinstance(matched, IndeterminateCondition)
        current_captures = nested_match.captures

    return _PatternMatch(
        IndeterminateCondition() if uncertain else True,
        current_captures,
    )


def _project_interface[T](
    pattern: ParameterizedTypePattern[T],
    source: ParameterizedTypeShape[TypeValue[T]],
    type_system: TypeSystem[T],
) -> tuple[TypeValue[T], ...] | None:
    target = type_system.generic_type(
        ParameterizedTypeShape(pattern.origin, ())
    ).unwrap()
    if target is None or target.family is not GenericFamily.SEQUENCE:
        return None

    native = ParameterizedTypeShape(
        expect_possible_type(source.origin, "generic origin must be a type").value,
        tuple(
            expect_possible_type(argument, "generic arguments must be types").value
            for argument in source.arguments
        ),
    )
    facts = type_system.generic_type(native).unwrap()
    if facts is None:
        raise UnsupportedExpressionSemanticError(
            "source generic origin is outside supported interface capture"
        )

    # Native tuple markers have no semantic element position. Keep the original
    # argument values so unknown symbols and union provenance survive projection.
    elements = sequence_elements(
        GenericType(
            facts.family,
            source.arguments[: len(facts.arguments)],
            variadic=facts.variadic,
        )
    )
    if elements is None:
        return None

    if len(pattern.arguments) != 1:
        raise UnsupportedExpressionSemanticError(
            "Sequence interface capture requires one argument"
        )

    return (union_type(elements, type_system, "Sequence elements must be types"),)


def _possible_captures[T](
    matches: tuple[_PatternMatch[T], ...], type_system: TypeSystem[T]
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


def _has_unbound_capture[T](
    pattern: TypePattern[T], bound_symbols: frozenset[TypeSymbol]
) -> bool:
    match pattern:
        case CaptureReference(symbol=symbol):
            return symbol not in bound_symbols
        case ParameterizedTypePattern(arguments=arguments):
            return any(
                _has_unbound_capture(argument, bound_symbols) for argument in arguments
            )
        case ExactTypePattern() | TypeValueReference():
            return False
        case _ as unreachable:
            assert_never(unreachable)


__all__ = ("map_values_match", "match_type_pattern")
