"""Legacy compiler schema evaluation retained until the semantic cutover."""

from typing import assert_never

from typeforge.compiler.stub_ir import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    CollectType,
    EachType,
    EqualPredicate,
    FieldType,
    FixedTuple,
    HomogeneousTuple,
    LiteralType,
    MapCase,
    MapFieldsType,
    MapType,
    MapValueType,
    NotPredicate,
    Predicate,
    RuntimeInputType,
    SchemaType,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    is_predicate,
    rewrite_type,
    walk_type,
)


def resolve_schema_type(expression: StubTypeExpression) -> StubTypeExpression:
    match expression:
        case TypeApplication(constructor, arguments):
            return TypeApplication(
                resolve_schema_type(constructor),
                tuple(resolve_schema_type(argument) for argument in arguments),
            )
        case FixedTuple(items):
            return FixedTuple(tuple(resolve_schema_type(item) for item in items))
        case HomogeneousTuple(item):
            return HomogeneousTuple(resolve_schema_type(item))
        case EachType(item):
            return EachType(resolve_schema_type(item))
        case CollectType(item):
            return CollectType(resolve_schema_type(item))
        case UnpackedType(item):
            return UnpackedType(resolve_schema_type(item))
        case UnionExpression(members):
            return union_types_for_schema(
                tuple(resolve_schema_type(member) for member in members)
            )
        case MapType(subject_expression, cases, default):
            subject = resolve_schema_type(subject_expression)
            if isinstance(subject_expression, RuntimeInputType):
                return union_types_for_schema(
                    (
                        *(resolve_schema_type(case.output_type) for case in cases),
                        resolve_schema_type(default),
                    )
                )

            members = (
                subject.members if isinstance(subject, UnionExpression) else (subject,)
            )
            return union_types_for_schema(
                tuple(
                    _resolve_schema_map_member(member, cases, default)
                    for member in members
                )
            )
        case FieldType(name, value, required, readonly):
            return FieldType(
                resolve_schema_type(name),
                resolve_schema_type(value),
                required,
                readonly,
            )
        case MapFieldsType(record, transform):
            return MapFieldsType(
                resolve_schema_type(record),
                resolve_schema_type(transform),
            )
        case SchemaType(item):
            return SchemaType(resolve_schema_type(item))
        case (
            TypeName()
            | TypeVariable()
            | LiteralType()
            | MapValueType()
            | RuntimeInputType()
        ):
            return expression
        case _ as unreachable:
            assert_never(unreachable)


def _resolve_schema_map_member(
    subject: StubTypeExpression,
    cases: tuple[MapCase, ...],
    default: StubTypeExpression,
) -> StubTypeExpression:
    for index, case in enumerate(cases):
        if is_predicate(case.test):
            result = resolve_schema_predicate(case.test)
            if result is True:
                return resolve_schema_type(case.output_type)

            if result is None:
                return union_types_for_schema(
                    (
                        resolve_schema_type(case.output_type),
                        _resolve_schema_map_member(
                            subject, cases[index + 1 :], default
                        ),
                    )
                )

            continue

        matched, capture = _match_schema_pattern(case.test, subject, None)
        if matched:
            return resolve_schema_type(
                _substitute_schema_capture(case.output_type, capture)
            )

    return resolve_schema_type(default)


def _match_schema_pattern(
    pattern: StubTypeExpression,
    subject: StubTypeExpression,
    capture: StubTypeExpression | None,
) -> tuple[bool, StubTypeExpression | None]:
    if isinstance(pattern, MapValueType):
        if capture is not None and capture != subject:
            return False, capture

        return True, subject

    if isinstance(pattern, TypeApplication) and isinstance(subject, TypeApplication):
        if resolve_schema_type(pattern.constructor) != resolve_schema_type(
            subject.constructor
        ) or len(pattern.arguments) != len(subject.arguments):
            return False, capture

        current = capture
        for nested_pattern, nested_subject in zip(
            pattern.arguments, subject.arguments, strict=True
        ):
            matched, current = _match_schema_pattern(
                nested_pattern, nested_subject, current
            )
            if not matched:
                return False, current

        return True, current

    return resolve_schema_type(pattern) == subject, capture


def _substitute_schema_capture(
    expression: StubTypeExpression,
    capture: StubTypeExpression | None,
) -> StubTypeExpression:
    return rewrite_type(
        expression,
        lambda current: (
            (capture or TypeName("object"))
            if isinstance(current, MapValueType)
            else None
        ),
    )


def resolve_schema_predicate(predicate: Predicate) -> bool | None:
    match predicate:
        case EqualPredicate(left, right):
            if _type_has_variable(left) or _type_has_variable(right):
                return None

            return resolve_schema_type(left) == resolve_schema_type(right)
        case AssignablePredicate(source, target):
            if _type_has_variable(source) or _type_has_variable(target):
                return None

            return _schema_assignable(
                resolve_schema_type(source), resolve_schema_type(target)
            )
        case AllPredicate(predicates):
            values = tuple(resolve_schema_predicate(item) for item in predicates)
            if False in values:
                return False

            return True if all(value is True for value in values) else None
        case AnyPredicate(predicates):
            values = tuple(resolve_schema_predicate(item) for item in predicates)
            if True in values:
                return True

            return False if all(value is False for value in values) else None
        case NotPredicate(item):
            value = resolve_schema_predicate(item)
            return None if value is None else not value
        case _ as unreachable:
            assert_never(unreachable)


def _schema_assignable(source: StubTypeExpression, target: StubTypeExpression) -> bool:
    if source == target or target == TypeName("object"):
        return True

    if isinstance(source, UnionExpression):
        return all(_schema_assignable(member, target) for member in source.members)

    if isinstance(target, UnionExpression):
        return any(_schema_assignable(source, member) for member in target.members)

    return False


def _type_has_variable(expression: StubTypeExpression) -> bool:
    return any(
        isinstance(node, TypeVariable | RuntimeInputType)
        for node in walk_type(expression)
    )


def union_types_for_schema(
    expressions: tuple[StubTypeExpression, ...],
) -> StubTypeExpression:
    members: list[StubTypeExpression] = []
    for expression in expressions:
        candidates = (
            expression.members
            if isinstance(expression, UnionExpression)
            else (expression,)
        )
        for candidate in candidates:
            if candidate != TypeName("Never") and candidate not in members:
                members.append(candidate)

    if not members:
        return TypeName("Never")

    if len(members) == 1:
        return members[0]

    return UnionExpression(tuple(members))
