"""Adapt supported runtime annotations directly to shared expressions."""

from dataclasses import dataclass
from typing import (
    Annotated,
    Any,
    Literal,
    TypeAliasType,
    TypeVar,
    TypeVarTuple,
    Union,
    Unpack,
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
from typeforge.pydantic._errors import SchemaIssue, UnresolvedAnnotationIssue
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
    return isinstance(value, TypeVar | TypeVarTuple) or any(
        has_parameters(arg) for arg in _type_arguments(value)
    )


def _type_arguments(value: object) -> tuple[object, ...]:
    """Literal values and Annotated metadata are opaque, not nested expressions."""
    match get_origin(value):
        case origin if origin is Literal:
            return ()

        case origin if origin is Annotated:
            return get_args(value)[:1]

        case _:
            return get_args(value)


def _is_unpack(value: object) -> bool:
    return get_origin(value) is Unpack or getattr(value, "__unpacked__", False) is True


def _contains_operator(value: object, seen: tuple[TypeAliasType, ...] = ()) -> bool:
    origin = get_origin(value) or value
    if any(origin is marker for marker in _MARKERS):
        return True

    if (
        isinstance(origin, TypeAliasType)
        and origin not in seen
        and _contains_operator(_alias_value(origin), (*seen, origin))
    ):
        return True

    return any(_contains_operator(arg, seen) for arg in _type_arguments(value))


def _alias_value(alias: TypeAliasType) -> object:
    try:
        return alias.__value__
    except NameError as error:
        raise UnresolvedAnnotationIssue(
            "unresolved_annotation",
            "parsing",
            alias,
            str(error),
            error.name or alias.__name__,
        ) from error


def uses_generic_fallback(
    expression: s.Expression[RuntimeType] | s.TypePattern[RuntimeType],
) -> bool:
    """Inspect bound operands, rather than parameters in the authored alias body."""
    match expression:
        case s.TypeReference(value=value) | s.ExactTypePattern(value=value):
            return has_parameters(value.annotation)

        case (
            s.ParameterizedTypeTemplate(origin=origin, arguments=arguments)
            | s.ParameterizedTypePattern(origin=origin, arguments=arguments)
        ):
            operands = arguments[:1] if origin.value is Annotated else arguments
            return any(uses_generic_fallback(argument) for argument in operands)

        case s.UnionExpression(members=members):
            return any(uses_generic_fallback(member) for member in members)

        case (
            s.EqualExpression(left=left, right=right)
            | s.AssignableExpression(source=left, target=right)
        ):
            return uses_generic_fallback(left) or uses_generic_fallback(right)

        case (
            s.AllExpression(conditions=conditions)
            | s.AnyExpression(conditions=conditions)
        ):
            return any(uses_generic_fallback(condition) for condition in conditions)

        case s.NotExpression(condition=condition):
            return uses_generic_fallback(condition)

        case s.MapExpression(subject=subject, cases=cases, default=default):
            return (
                uses_generic_fallback(subject)
                or any(
                    uses_generic_fallback(case.test)
                    or uses_generic_fallback(case.output)
                    for case in cases
                )
                or (default is not None and uses_generic_fallback(default))
            )

        case _:
            return False


_ADAPTATION_ERRORS: tuple[type[SchemaIssue | s.SemanticIssue], ...] = (
    SchemaIssue,
    s.SemanticIssue,
)


@safe_result(errors=_ADAPTATION_ERRORS)
def adapt_annotation(source: object) -> AdaptedAnnotation:
    adapter = _AnnotationAdapter()
    expression = adapter.adapt(source)
    return AdaptedAnnotation(expression, adapter.origins)


type AnnotationBindingMap = dict[
    object, s.Expression[RuntimeType] | tuple[s.Expression[RuntimeType], ...]
]


class _AnnotationAdapter:
    """Adapt one annotation tree, retaining the authored origin of each node."""

    def __init__(
        self,
        origins: dict[int, object] | None = None,
        bindings: AnnotationBindingMap | None = None,
        aliases: tuple[TypeAliasType, ...] | None = None,
    ) -> None:
        self.origins: dict[int, object] = origins or {}
        self.bindings: AnnotationBindingMap = bindings or {}
        self.aliases: tuple[TypeAliasType, ...] = aliases or ()

    def adapt(self, value: object) -> s.Expression[RuntimeType]:
        expression = self._lower(value)
        self.origins[id(expression)] = value
        return expression

    def _lower(self, value: object) -> s.Expression[RuntimeType]:
        origin = get_origin(value) or value
        arguments: tuple[object, ...] = get_args(value)
        if isinstance(value, TypeVar | TypeVarTuple):
            return self._parameter(value)

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
            return self._alias(value, origin, arguments)

        return self._ordinary_type(value, origin, arguments)

    def _parameter(self, value: TypeVar | TypeVarTuple) -> s.Expression[RuntimeType]:
        bound = self.bindings.get(value)
        if isinstance(bound, tuple) or isinstance(value, TypeVarTuple):
            raise SchemaIssue(
                "alias_arguments",
                "parsing",
                value,
                "A variadic parameter must be bound and unpacked",
            )

        return bound if bound is not None else self._type_variable(value)

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
                message="A dependent generic fallback requires a bound alias parameter",
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
            if default is not None:
                raise invalid(value, "Map entries cannot follow Default")

            adapted = self._map_entry(entry, expression=value)
            if isinstance(adapted, s.CaseExpression):
                cases.append(adapted)
            else:
                default = adapted

        return s.MapExpression(self.adapt(arguments[0]), tuple(cases), default)

    def _map_entry(
        self, value: object, *, expression: object
    ) -> s.CaseExpression[RuntimeType] | s.Expression[RuntimeType]:
        origin = get_origin(value) or value
        parts: tuple[object, ...] = get_args(value)
        if origin is Case and len(parts) == 2:
            return s.CaseExpression(self._case_test(parts[0]), self.adapt(parts[1]))

        if origin is Default and len(parts) == 1:
            return self.adapt(parts[0])

        if isinstance(origin, TypeAliasType) and origin not in _MARKERS:
            child = self._alias_adapter(value, origin, parts)
            return child._map_entry(_alias_value(origin), expression=expression)

        raise invalid(
            expression,
            "Map entries must be Case[test, output] followed by "
            "an optional Default[output]",
        )

    def _case_test(
        self, value: object
    ) -> s.Expression[RuntimeType] | s.TypePattern[RuntimeType]:
        expression = self.adapt(value)
        result = self._pattern(expression) or expression

        self.origins[id(result)] = value
        return result

    def _pattern(
        self, expression: s.Expression[RuntimeType]
    ) -> s.TypePattern[RuntimeType] | None:
        match expression:
            case s.ValueReference():
                return s.CaptureValuePattern()

            case s.TypeReference(value=value):
                return s.ExactTypePattern(value)

            case s.UnionExpression(members=members):
                values = tuple(
                    member.value
                    for member in members
                    if isinstance(member, s.TypeReference)
                )
                if len(values) == len(members):
                    return s.ExactTypePattern(
                        RUNTIME_TYPE_SYSTEM.union(values).unwrap()
                    )

            case s.ParameterizedTypeTemplate(origin=origin, arguments=arguments):
                if origin.value is Annotated:
                    return self._pattern(arguments[0])

                patterns = tuple(self._pattern(argument) for argument in arguments)
                if all(pattern is not None for pattern in patterns):
                    return s.ParameterizedTypePattern(
                        origin,
                        tuple(pattern for pattern in patterns if pattern is not None),
                    )
            case _:
                raise invalid(
                    expression,
                    f"Expression [{expression.__class__.__name__}] not patternable",
                )

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

    def _alias(
        self, value: object, alias: TypeAliasType, arguments: tuple[object, ...]
    ) -> s.Expression[RuntimeType]:
        if not _contains_operator(value):
            return self._ordinary_type(value, alias, arguments)

        child = self._alias_adapter(value, alias, arguments)
        return child.adapt(_alias_value(alias))

    def _alias_adapter(
        self, value: object, alias: TypeAliasType, arguments: tuple[object, ...]
    ) -> _AnnotationAdapter:
        if alias in self.aliases:
            raise SchemaIssue(
                "alias_cycle",
                "parsing",
                value,
                "recursive aliases containing Typeforge operators are not supported",
            )

        child = _AnnotationAdapter(
            origins=self.origins, bindings=self.bindings, aliases=(*self.aliases, alias)
        )
        self._bind_alias(value, alias, arguments, child)
        return child

    def _bind_alias(
        self,
        value: object,
        alias: TypeAliasType,
        arguments: tuple[object, ...],
        child: _AnnotationAdapter,
    ) -> None:
        supplied = self._arguments(arguments)
        index = 0
        for position, parameter in enumerate(alias.__type_params__):
            if isinstance(parameter, TypeVarTuple):
                fixed_after = len(alias.__type_params__) - position - 1
                end = max(index, len(supplied) - fixed_after)
                child.bindings[parameter] = (
                    child._variadic_fallback(parameter)
                    if get_origin(value) is None
                    else supplied[index:end]
                )
                index = end

            elif index < len(supplied):
                child.bindings[parameter] = supplied[index]
                index += 1

            elif parameter.has_default():
                child.bindings[parameter] = child.adapt(parameter.__default__)

            elif get_origin(value) is None and isinstance(parameter, TypeVar):
                child.bindings[parameter] = child._type_variable(parameter)

            else:
                raise SchemaIssue(
                    "alias_arguments",
                    "parsing",
                    value,
                    "Not enough arguments for generic alias",
                )

        if index != len(supplied):
            raise SchemaIssue(
                "alias_arguments",
                "parsing",
                value,
                "Too many arguments for generic alias",
            )

    def _variadic_fallback(
        self, parameter: TypeVarTuple
    ) -> tuple[s.Expression[RuntimeType], ...]:
        if parameter.has_default():
            return self._arguments((parameter.__default__,))

        raise SchemaIssue(
            "alias_arguments",
            "parsing",
            parameter,
            "An unbound variadic alias requires specialization or a finite default",
        )

    def _arguments(
        self, arguments: tuple[object, ...]
    ) -> tuple[s.Expression[RuntimeType], ...]:
        result: list[s.Expression[RuntimeType]] = []
        for argument in arguments:
            if get_origin(argument) is Unpack:
                unpacked = get_args(argument)
                if len(unpacked) != 1:
                    raise invalid(argument, "Unpack requires exactly one argument")

                result.extend(self._unpack(unpacked[0]))

            elif getattr(argument, "__unpacked__", False) is True:
                result.extend(self._unpack(argument))

            else:
                result.append(self.adapt(argument))

        return tuple(result)

    def _unpack(self, value: object) -> tuple[s.Expression[RuntimeType], ...]:
        if isinstance(value, TypeVarTuple):
            bound = self.bindings.get(value)
            if isinstance(bound, tuple):
                return bound

        elif get_origin(value) is tuple and Ellipsis not in get_args(value):
            return self._arguments(get_args(value))

        raise SchemaIssue(
            "alias_arguments",
            "parsing",
            value,
            "Unpack requires a bound variadic parameter or a finite tuple",
        )

    def _ordinary_type(
        self, value: object, origin: object, arguments: tuple[object, ...]
    ) -> s.TypeReference[RuntimeType] | s.ParameterizedTypeTemplate[RuntimeType]:
        if arguments and (
            has_parameters(value)
            or _contains_operator(value)
            or any(_is_unpack(argument) for argument in arguments)
        ):
            return s.ParameterizedTypeTemplate(
                concrete_type(origin),
                self._arguments(arguments),
            )

        return s.TypeReference(concrete_type(value))


def invalid(expression: object, message: str) -> SchemaIssue:
    return SchemaIssue("invalid_marker", "parsing", expression, message)
