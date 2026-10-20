"""Finite predicate candidates and defaults for callable specialization."""

from dataclasses import dataclass

from returns.result import Failure, Result, Success

from typeforge.compiler.specialization._expressions import (
    collect_variable_names,
    has_variable,
    substitute_scalar,
)
from typeforge.compiler.specialization._models import LoweringErrorCode
from typeforge.compiler.stub_ir import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    EqualPredicate,
    MapCase,
    MapType,
    NotPredicate,
    Predicate,
    StubTypeExpression,
    TypeName,
    TypeVariable,
    UnionExpression,
    is_predicate,
)


@dataclass(frozen=True, slots=True)
class PredicateMatch:
    input_type: StubTypeExpression
    result: bool


def map_specializations(mapping: MapType, controller: str) -> tuple[MapCase, ...]:
    candidates: list[StubTypeExpression] = []
    for case in mapping.cases:
        tests = (
            tuple(
                match.input_type for match in predicate_matches(case.test, controller)
            )
            if is_predicate(case.test)
            else (case.test,)
        )
        for test in tests:
            if test not in candidates:
                candidates.append(test)

    return tuple(
        MapCase(candidate, _map_output_for_input(mapping, controller, candidate))
        for candidate in candidates
    )


def map_default_output(mapping: MapType, controller: str) -> StubTypeExpression:
    return next(
        (
            case.output_type
            for case in mapping.cases
            if is_predicate(case.test)
            and _predicate_result_for_input(
                case.test,
                controller,
                TypeVariable(controller),
            )
        ),
        TypeName("Never") if mapping.default is None else mapping.default,
    )


def _map_output_for_input(
    mapping: MapType,
    controller: str,
    input_type: StubTypeExpression,
) -> StubTypeExpression:
    for case in mapping.cases:
        matched = (
            _predicate_result_for_input(case.test, controller, input_type)
            if is_predicate(case.test)
            else case.test == input_type
        )
        if matched:
            return case.output_type

    return TypeName("Never") if mapping.default is None else mapping.default


def _predicate_result_for_input(
    predicate: Predicate,
    controller: str,
    input_type: StubTypeExpression,
) -> bool:
    resolved = _resolve_predicate_for_input(predicate, controller, input_type)
    if resolved is not None:
        return resolved

    match = next(
        (
            candidate
            for candidate in predicate_matches(predicate, controller)
            if candidate.input_type == input_type
        ),
        None,
    )
    return predicate_default(predicate) if match is None else match.result


def _resolve_predicate_for_input(
    predicate: Predicate,
    controller: str,
    input_type: StubTypeExpression,
) -> bool | None:
    match predicate:
        case EqualPredicate(left, right):
            return substitute_scalar(left, controller, input_type) == substitute_scalar(
                right, controller, input_type
            )
        case AssignablePredicate(source, target):
            return _known_assignability(
                substitute_scalar(source, controller, input_type),
                substitute_scalar(target, controller, input_type),
            )
        case AllPredicate(predicates):
            values = tuple(
                _resolve_predicate_for_input(item, controller, input_type)
                for item in predicates
            )
            if False in values:
                return False

            return True if all(value is True for value in values) else None
        case AnyPredicate(predicates):
            values = tuple(
                _resolve_predicate_for_input(item, controller, input_type)
                for item in predicates
            )
            if True in values:
                return True

            return False if all(value is False for value in values) else None
        case NotPredicate(item):
            value = _resolve_predicate_for_input(item, controller, input_type)
            return None if value is None else not value


def _known_assignability(
    source: StubTypeExpression,
    target: StubTypeExpression,
) -> bool | None:
    if source == target or target == TypeName("object"):
        return True

    if isinstance(source, UnionExpression):
        values = tuple(
            _known_assignability(member, target) for member in source.members
        )
        if False in values:
            return False

        return True if all(value is True for value in values) else None

    if isinstance(target, UnionExpression):
        values = tuple(
            _known_assignability(source, member) for member in target.members
        )
        if True in values:
            return True

        return False if all(value is False for value in values) else None

    return (
        None
        if collect_variable_names(source) or collect_variable_names(target)
        else False
    )


def predicate_default(predicate: Predicate) -> bool:
    if isinstance(predicate, NotPredicate):
        return not predicate_default(predicate.predicate)

    if isinstance(predicate, AllPredicate):
        return all(predicate_default(item) for item in predicate.predicates)

    if isinstance(predicate, AnyPredicate):
        return any(predicate_default(item) for item in predicate.predicates)

    return False


def predicate_controller(
    predicate: Predicate,
) -> Result[str, LoweringErrorCode]:
    names = _predicate_variable_names(predicate)
    if len(names) != 1:
        return Failure(LoweringErrorCode.UNSUPPORTED_PREDICATE)

    return Success(names[0])


def _predicate_variable_names(predicate: Predicate) -> tuple[str, ...]:
    names: list[str] = []

    def add(expression: StubTypeExpression) -> None:
        for name in collect_variable_names(expression):
            if name not in names:
                names.append(name)

    def visit(current: Predicate) -> None:
        if isinstance(current, EqualPredicate):
            add(current.left)
            add(current.right)
        elif isinstance(current, AssignablePredicate):
            add(current.source)
            add(current.target)
        elif isinstance(current, AllPredicate | AnyPredicate):
            for child in current.predicates:
                visit(child)
        else:
            visit(current.predicate)

    visit(predicate)
    return tuple(names)


def predicate_matches(
    predicate: Predicate, controller: str
) -> tuple[PredicateMatch, ...]:
    if isinstance(predicate, EqualPredicate):
        if predicate.left == TypeVariable(controller) and not has_variable(
            predicate.right, controller
        ):
            return (PredicateMatch(predicate.right, True),)

        if predicate.right == TypeVariable(controller) and not has_variable(
            predicate.left, controller
        ):
            return (PredicateMatch(predicate.left, True),)

        return ()

    if isinstance(predicate, AssignablePredicate):
        if predicate.source == TypeVariable(controller) and not has_variable(
            predicate.target, controller
        ):
            return (PredicateMatch(predicate.target, True),)

        return ()

    if isinstance(predicate, NotPredicate):
        return tuple(
            PredicateMatch(match.input_type, not match.result)
            for match in predicate_matches(predicate.predicate, controller)
        )

    child_matches = tuple(
        predicate_matches(child, controller) for child in predicate.predicates
    )
    if isinstance(predicate, AllPredicate):
        true_matches = _common_matches(child_matches, True)
        false_matches = _matching_results(child_matches, False)
        return _unique_matches((*true_matches, *false_matches))

    true_matches = _matching_results(child_matches, True)
    false_matches = _common_matches(child_matches, False)
    return _unique_matches((*true_matches, *false_matches))


def predicate_is_supported(predicate: Predicate, controller: str) -> bool:
    variable = TypeVariable(controller)
    if isinstance(predicate, EqualPredicate):
        if predicate.left == variable and predicate.right == variable:
            return True

        return (
            predicate.left == variable and not has_variable(predicate.right, controller)
        ) or (
            predicate.right == variable and not has_variable(predicate.left, controller)
        )

    if isinstance(predicate, AssignablePredicate):
        return predicate.source == variable and not has_variable(
            predicate.target, controller
        )

    if isinstance(predicate, NotPredicate):
        return predicate_is_supported(predicate.predicate, controller)

    return all(
        predicate_is_supported(child, controller) for child in predicate.predicates
    )


def _matching_results(
    groups: tuple[tuple[PredicateMatch, ...], ...], result: bool
) -> tuple[PredicateMatch, ...]:
    return tuple(match for group in groups for match in group if match.result is result)


def _common_matches(
    groups: tuple[tuple[PredicateMatch, ...], ...], result: bool
) -> tuple[PredicateMatch, ...]:
    if not groups:
        return ()

    first = tuple(match for match in groups[0] if match.result is result)
    return tuple(
        match for match in first if all(match in group for group in groups[1:])
    )


def _unique_matches(
    matches: tuple[PredicateMatch, ...],
) -> tuple[PredicateMatch, ...]:
    return tuple(dict.fromkeys(matches))
