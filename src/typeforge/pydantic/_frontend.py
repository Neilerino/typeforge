"""Adapt supported runtime annotations directly to shared expressions."""

from dataclasses import dataclass
from typing import (
    Annotated,
    Any,
    Literal,
    TypeAliasType,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

from typeforge import (
    All,
    Assignable,
    Case,
    Collect,
    Default,
    Drop,
    Each,
    Equal,
    Field,
    Key,
    Map,
    MapFields,
    Not,
    OptionalField,
    ReadonlyField,
    Value,
)
from typeforge import Any as AnyCondition
from typeforge import semantics as s
from typeforge.pydantic import Input
from typeforge.pydantic._errors import SchemaIssue
from typeforge.pydantic._policy import generic_fallback
from typeforge.pydantic._type_system import (
    RUNTIME_TYPE_SYSTEM,
    RuntimeType,
    concrete_type,
)
from typeforge.utils.error_handling import safe_result


@dataclass(frozen=True, slots=True)
class AdaptedAnnotation:
    expression: s.Expression[RuntimeType]
    origins: dict[int, object]


_MARKERS = (
    Map,
    Case,
    Default,
    Equal,
    Assignable,
    All,
    AnyCondition,
    Not,
    Input,
    Key,
    Value,
    MapFields,
    Field,
    OptionalField,
    ReadonlyField,
    Drop,
    Each,
    Collect,
)


def has_parameters(value: object) -> bool:
    return isinstance(value, TypeVar) or any(
        has_parameters(arg) for arg in get_args(value)
    )


def _contains_operator(value: object, seen: tuple[TypeAliasType, ...] = ()) -> bool:
    origin = get_origin(value) or value
    if any(origin is marker for marker in _MARKERS):
        return True

    if isinstance(origin, TypeAliasType) and origin not in seen:
        return _contains_operator(origin.__value__, (*seen, origin))

    return any(_contains_operator(arg, seen) for arg in get_args(value))


_ADAPTATION_ERRORS: tuple[type[SchemaIssue | s.SemanticIssue], ...] = (
    SchemaIssue,
    s.SemanticIssue,
)


@safe_result(errors=_ADAPTATION_ERRORS)
def adapt_annotation(source: object) -> AdaptedAnnotation:
    adapter = _AnnotationAdapter()
    expression = adapter.adapt(source)
    return AdaptedAnnotation(expression, adapter.origins)


class _AnnotationAdapter:
    """Adapt one annotation tree, retaining the authored origin of each node."""

    def __init__(self) -> None:
        self.origins: dict[int, object] = {}

    def adapt(self, value: object) -> s.Expression[RuntimeType]:
        expression = self._lower(value)
        self.origins[id(expression)] = value
        return expression

    def _lower(self, value: object) -> s.Expression[RuntimeType]:
        origin = get_origin(value) or value
        arguments: tuple[object, ...] = get_args(value)
        if isinstance(value, TypeVar):
            return self._type_variable(value)

        if origin is Map:
            return self._map(value, arguments)

        if origin is Equal or origin is Assignable:
            return self._binary_predicate(value, origin, arguments)

        if origin is All or origin is AnyCondition:
            return self._conditions(origin, arguments)

        if origin is Not:
            return self._not(value, arguments)

        if origin is Key:
            return s.KeyReference()

        if origin is Value:
            return s.ValueReference()

        if any(origin is marker for marker in _MARKERS):
            raise SchemaIssue(
                code="unsupported_relationship",
                phase="parsing",
                expression=value,
                message=(
                    "This operator is not supported by the replacement pipeline yet"
                ),
            )

        if origin is Annotated:
            return self._annotated(arguments)

        if origin is Union:
            return self._union(arguments)

        if origin is Literal:
            return s.TypeReference(concrete_type(value))

        if isinstance(origin, TypeAliasType):
            return self._alias(value)

        return self._ordinary_type(value, origin, arguments)

    def _type_variable(self, value: TypeVar) -> s.TypeReference[RuntimeType]:
        default = (
            self._type_argument(value.__default__, parameter=value)
            if value.has_default()
            else None
        )
        bound = (
            self._type_argument(value.__bound__, parameter=value)
            if value.__bound__ is not None
            else None
        )
        choices = generic_fallback(
            default=default,
            constraints=tuple(
                self._type_argument(item, parameter=value)
                for item in value.__constraints__
            ),
            bound=bound,
            any_type=concrete_type(Any),
        )
        effective = RUNTIME_TYPE_SYSTEM.union(choices).unwrap().value
        return s.TypeReference(RuntimeType(effective, value))

    def _type_argument(self, item: object, *, parameter: TypeVar) -> RuntimeType:
        if isinstance(item, TypeVar):
            raise SchemaIssue(
                code="unsupported_relationship",
                phase="parsing",
                expression=parameter,
                message="Dependent generic defaults require alias binding support",
            )

        return concrete_type(item)

    def _map(
        self, value: object, arguments: tuple[object, ...]
    ) -> s.MapExpression[RuntimeType]:
        if not arguments:
            raise invalid(value, "Map requires a subject")

        cases: list[s.CaseExpression[RuntimeType]] = []
        default: s.Expression[RuntimeType] | None = None
        for entry in arguments[1:]:
            entry_origin = get_origin(entry)
            parts: tuple[object, ...] = get_args(entry)
            if entry_origin is Case and len(parts) == 2 and default is None:
                cases.append(
                    s.CaseExpression(self.adapt(parts[0]), self.adapt(parts[1]))
                )
            elif entry_origin is Default and len(parts) == 1 and default is None:
                default = self.adapt(parts[0])
            else:
                raise invalid(
                    value,
                    "Map entries must be Case[test, output] followed by "
                    "an optional Default[output]",
                )

        return s.MapExpression(self.adapt(arguments[0]), tuple(cases), default)

    def _binary_predicate(
        self, value: object, origin: object, arguments: tuple[object, ...]
    ) -> s.EqualExpression[RuntimeType] | s.AssignableExpression[RuntimeType]:
        if len(arguments) != 2:
            raise invalid(value, "Binary predicates require two operands")

        left, right = (self.adapt(arg) for arg in arguments)
        return (
            s.EqualExpression(left, right)
            if origin is Equal
            else s.AssignableExpression(left, right)
        )

    def _conditions(
        self, origin: object, arguments: tuple[object, ...]
    ) -> s.AllExpression[RuntimeType] | s.AnyExpression[RuntimeType]:
        conditions = tuple(self.adapt(arg) for arg in arguments)
        return (
            s.AllExpression(conditions)
            if origin is All
            else s.AnyExpression(conditions)
        )

    def _not(
        self, value: object, arguments: tuple[object, ...]
    ) -> s.NotExpression[RuntimeType]:
        if len(arguments) != 1:
            raise invalid(value, "Not requires one condition")

        return s.NotExpression(self.adapt(arguments[0]))

    def _annotated(
        self, arguments: tuple[object, ...]
    ) -> s.ParameterizedTypeTemplate[RuntimeType]:
        return s.ParameterizedTypeTemplate(
            concrete_type(Annotated),
            (
                self.adapt(arguments[0]),
                *(
                    s.TypeReference(concrete_type(metadata))
                    for metadata in arguments[1:]
                ),
            ),
        )

    def _union(self, arguments: tuple[object, ...]) -> s.UnionExpression[RuntimeType]:
        return s.UnionExpression(tuple(self.adapt(arg) for arg in arguments))

    def _alias(self, value: object) -> s.TypeReference[RuntimeType]:
        if _contains_operator(value):
            raise SchemaIssue(
                "unsupported_relationship",
                "parsing",
                value,
                "Typeforge alias expansion is not available in this slice",
            )

        return s.TypeReference(concrete_type(value))

    def _ordinary_type(
        self, value: object, origin: object, arguments: tuple[object, ...]
    ) -> s.TypeReference[RuntimeType] | s.ParameterizedTypeTemplate[RuntimeType]:
        if arguments:
            if _contains_operator(value):
                raise SchemaIssue(
                    "unsupported_relationship",
                    "parsing",
                    value,
                    "Nested Typeforge templates require structural adaptation",
                )

            if has_parameters(value):
                return s.ParameterizedTypeTemplate(
                    concrete_type(origin),
                    tuple(self.adapt(arg) for arg in arguments),
                )

        return s.TypeReference(concrete_type(value))


def invalid(expression: object, message: str) -> SchemaIssue:
    return SchemaIssue("invalid_marker", "parsing", expression, message)
