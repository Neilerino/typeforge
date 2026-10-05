"""Adapt supported runtime annotations directly to shared expressions."""

from dataclasses import dataclass, replace
from typing import (
    Annotated,
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
    Collect,
    Drop,
    Each,
    Field,
    Is,
    Key,
    MapFields,
    OptionalField,
    ReadonlyField,
    Value,
)
from typeforge import semantics as s
from typeforge._capture import Capture, CaptureSymbol
from typeforge._map import normalize_selector_literal
from typeforge._markers import All, Assignable, Case, Default, Equal, Map, Not
from typeforge._markers import Any as AnyCondition
from typeforge._type_function import SymbolicTypeParameter
from typeforge.pydantic._errors import SchemaIssue, UnresolvedAnnotationIssue
from typeforge.pydantic._markers import Input
from typeforge.pydantic._type_system import (
    RUNTIME_TYPE_SYSTEM,
    RuntimeType,
    concrete_type,
    runtime_type,
)
from typeforge.utils.error_handling import safe_result
from typeforge.utils.iteration import tmap


@dataclass(frozen=True, slots=True)
class AdaptedAnnotation:
    expression: s.Expression[RuntimeType]
    origins: dict[int, object]


_MARKERS = (
    Capture,
    SymbolicTypeParameter,
    Map,
    Case,
    Default,
    Equal,
    Is,
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
        case s.AnnotatedExpression(value=value):
            return uses_generic_fallback(value)

        case s.TypeReference(value=value) | s.ExactTypePattern(value=value):
            return has_parameters(value.annotation)

        case (
            s.ParameterizedTypeTemplate(arguments=arguments)
            | s.ParameterizedTypePattern(arguments=arguments)
        ):
            return any(uses_generic_fallback(argument) for argument in arguments)

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
        self.origins: dict[int, object] = {} if origins is None else origins
        self.bindings: AnnotationBindingMap = bindings or {}
        self.aliases: tuple[TypeAliasType, ...] = aliases or ()

    def adapt(
        self,
        value: object,
        *,
        selector_subject: s.Expression[RuntimeType] | None = None,
    ) -> s.Expression[RuntimeType]:
        expression = self._lower(value, selector_subject=selector_subject)
        self.origins[id(expression)] = value
        return expression

    def _lower(
        self, value: object, *, selector_subject: s.Expression[RuntimeType] | None
    ) -> s.Expression[RuntimeType]:
        origin = get_origin(value) or value
        arguments: tuple[object, ...] = get_args(value)
        if origin is Capture:
            if len(arguments) != 1 or not isinstance(arguments[0], CaptureSymbol):
                raise invalid(value, "invalid capture declaration")

            symbol = arguments[0]
            return s.CaptureReference(
                s.TypeSymbol(("runtime-capture", str(id(symbol))), symbol.name)
            )

        if origin is SymbolicTypeParameter:
            if len(arguments) != 1 or not isinstance(arguments[0], TypeVar):
                raise invalid(value, "invalid symbolic type parameter")

            return self._parameter(arguments[0])

        if isinstance(value, TypeVar | TypeVarTuple):
            return self._parameter(value)

        if origin is Map:
            return self._map(value, arguments)

        if origin is MapFields:
            if len(arguments) != 2:
                raise invalid(value, "MapFields requires a record and a transform")

            return s.MapFieldsExpression(
                self.adapt(arguments[0]), self.adapt(arguments[1])
            )

        if origin in (Field, OptionalField, ReadonlyField):
            return self._field(value, origin, arguments)

        if origin is Drop:
            return s.DropExpression()

        if origin is Is:
            if len(arguments) != 1:
                raise invalid(value, "Is requires one type argument")

            return self._binary_predicate(value, Equal, arguments, selector_subject)

        if origin is Equal or origin is Assignable:
            return self._binary_predicate(value, origin, arguments, selector_subject)

        if origin is All or origin is AnyCondition:
            return self._conditions(origin, arguments, selector_subject)

        if origin is Not:
            return self._not(value, arguments, selector_subject)

        if origin is Key:
            return s.KeyReference()

        if origin is Value:
            return s.ValueReference()

        if origin is Input:
            return s.InputReference()

        if any(origin is marker for marker in _MARKERS):
            raise SchemaIssue(
                code="unsupported_relationship",
                phase="parsing",
                expression=value,
                message="This operator has no Pydantic model-field semantics",
            )

        if origin is Annotated:
            return self._annotated(arguments, selector_subject)

        if origin is Union:
            return self._union(arguments)

        if origin is Literal:
            return s.TypeReference(concrete_type(value))

        if isinstance(origin, TypeAliasType):
            return self._alias(value, origin, arguments, selector_subject)

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
        return s.TypeReference(runtime_type(value).unwrap())

    def _map(
        self, value: object, arguments: tuple[object, ...]
    ) -> s.MapExpression[RuntimeType]:
        if not arguments:
            raise invalid(value, "Map requires a subject")

        subject = self._selection_type(self.adapt(arguments[0]))
        cases: list[s.CaseExpression[RuntimeType]] = []
        default: s.Expression[RuntimeType] | None = None
        for entry in arguments[1:]:
            if default is not None:
                raise invalid(
                    value, "Map fallback must be last; no branch may follow it"
                )

            adapted = self._map_entry(entry, expression=value, subject=subject)
            if isinstance(adapted, s.CaseExpression):
                cases.append(adapted)
            else:
                default = adapted

        if isinstance(subject, s.KeyReference | s.FieldName):
            cases = [
                replace(case, test=self._name_expression(case.test)) for case in cases
            ]

        return s.MapExpression(subject, tuple(cases), default)

    def _input_test(self, test: s.Expression[RuntimeType]) -> s.Expression[RuntimeType]:
        """Expose selection types while ignoring raw-test annotation metadata."""
        test = self._selection_type(test)
        match test:
            case s.AnnotatedExpression(value=value):
                return self._input_test(value)

            case s.UnionExpression(members=members):
                return replace(
                    test, members=tuple(self._input_test(item) for item in members)
                )

            case _:
                pass

        return test

    def _selection_type(
        self, expression: s.Expression[RuntimeType]
    ) -> s.Expression[RuntimeType]:
        """Expand ordinary aliases only where Typeforge needs their type identity.

        Output aliases remain annotations delegated to Pydantic. Selection uses
        the same argument-binding and cycle boundary as operator aliases.
        """
        match expression:
            case s.TypeReference(value=value):
                origin = get_origin(value.value) or value.value
                if isinstance(origin, TypeAliasType):
                    result = self._selection_alias(value.annotation, origin)
                elif isinstance(value.annotation, TypeVar):
                    return expression
                elif _type_arguments(value.value):
                    result = self._selection_type(
                        s.ParameterizedTypeTemplate(
                            concrete_type(origin),
                            tuple(self.adapt(arg) for arg in get_args(value.value)),
                        )
                    )
                else:
                    return expression

            case s.AnnotatedExpression(value=value):
                result = replace(expression, value=self._selection_type(value))

            case s.UnionExpression(members=members):
                result = replace(
                    expression,
                    members=tuple(self._selection_type(arg) for arg in members),
                )

            case s.ParameterizedTypeTemplate(origin=origin, arguments=arguments):
                if isinstance(origin.value, TypeAliasType):
                    authored = self.origins[id(expression)]
                    result = self._selection_alias(authored, origin.value)
                else:
                    result = replace(
                        expression,
                        arguments=tuple(self._selection_type(arg) for arg in arguments),
                    )

            case s.MapExpression(cases=cases, default=default):
                result = replace(
                    expression,
                    cases=tuple(
                        replace(case, output=self._selection_type(case.output))
                        for case in cases
                    ),
                    default=None if default is None else self._selection_type(default),
                )

            case _:
                return expression

        self.origins[id(result)] = self.origins.get(id(expression), expression)
        return result

    def _selection_alias(
        self, value: object, alias: TypeAliasType
    ) -> s.Expression[RuntimeType]:
        child = self._alias_adapter(
            value, alias, get_args(value), expand_arguments=True
        )
        return child._selection_type(child.adapt(_alias_value(alias)))

    def _field(
        self, value: object, origin: object, arguments: tuple[object, ...]
    ) -> (
        s.FieldExpression[RuntimeType]
        | s.OptionalFieldExpression[RuntimeType]
        | s.ReadonlyFieldExpression[RuntimeType]
    ):
        if len(arguments) != 2:
            raise invalid(value, "Field requires a name and a type")

        name = self._name_expression(self.adapt(arguments[0]))
        output = self.adapt(arguments[1])
        if origin is OptionalField:
            return s.OptionalFieldExpression(name, output)

        if origin is ReadonlyField:
            return s.ReadonlyFieldExpression(name, output)

        return s.FieldExpression(name, output)

    def _name_expression(
        self, expression: s.Expression[RuntimeType] | s.TypePattern[RuntimeType]
    ) -> s.Expression[RuntimeType]:
        result = self._lower_name(expression)
        self.origins[id(result)] = self.origins.get(id(expression), expression)
        return result

    def _lower_name(
        self, expression: s.Expression[RuntimeType] | s.TypePattern[RuntimeType]
    ) -> s.Expression[RuntimeType]:
        match expression:
            case s.AnnotatedExpression(value=value):
                return self._name_expression(value)

            case s.TypeReference(value=value) | s.ExactTypePattern(value=value):
                values = get_args(value.value)
                if (
                    get_origin(value.value) is Literal
                    and len(values) == 1
                    and isinstance(values[0], str)
                ):
                    return s.FieldName(values[0])

                return s.TypeReference(value)

            case s.MapExpression(cases=cases, default=default):
                return replace(
                    expression,
                    cases=tmap(
                        lambda c: replace(c, output=self._name_expression(c.output)),
                        cases,
                    ),
                    default=None if default is None else self._name_expression(default),
                )

            case s.ParameterizedTypePattern() | s.AlternativeTypePattern():
                raise invalid(
                    self.origins[id(expression)],
                    "A field name must be Key or a string Literal",
                )

            case _:
                return expression

    def _map_entry(
        self, value: object, *, expression: object, subject: s.Expression[RuntimeType]
    ) -> s.CaseExpression[RuntimeType] | s.Expression[RuntimeType]:
        origin = get_origin(value) or value
        parts: tuple[object, ...] = get_args(value)
        if origin is Case and len(parts) == 2:
            test = (
                self._input_test(self.adapt(parts[0], selector_subject=subject))
                if isinstance(subject, s.InputReference)
                else self._case_test(parts[0], subject)
            )
            return s.CaseExpression(test, self.adapt(parts[1]))

        if origin is Default and len(parts) == 1:
            return self.adapt(parts[0])

        if isinstance(origin, TypeAliasType) and origin not in _MARKERS:
            child = self._alias_adapter(value, origin, parts)
            return child._map_entry(
                _alias_value(origin), expression=expression, subject=subject
            )

        raise invalid(
            expression,
            "Map entries must use selector: output followed by "
            "an optional fallback (...: output)",
        )

    def _case_test(
        self, value: object, subject: s.Expression[RuntimeType]
    ) -> s.Expression[RuntimeType] | s.TypePattern[RuntimeType]:
        expression = self._selection_type(self.adapt(value, selector_subject=subject))
        result = self._pattern(expression) or expression
        if isinstance(result, s.ExactTypePattern):
            result = s.TypeReference(result.value)

        self.origins[id(result)] = value
        return result

    def _pattern(
        self, expression: s.Expression[RuntimeType]
    ) -> s.TypePattern[RuntimeType] | None:
        match expression:
            case s.AnnotatedExpression(value=value):
                return self._pattern(value)

            case s.ValueReference():
                raise invalid(
                    self.origins[id(expression)],
                    "Value is a field reference; "
                    "declare Capture for structural matching",
                )

            case s.CaptureReference():
                return expression

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

                patterns = tuple(self._pattern(member) for member in members)
                if all(pattern is not None for pattern in patterns):
                    return s.AlternativeTypePattern(
                        tuple(pattern for pattern in patterns if pattern is not None)
                    )

            case s.ParameterizedTypeTemplate(origin=origin, arguments=arguments):
                patterns = tuple(self._pattern(argument) for argument in arguments)
                if all(pattern is not None for pattern in patterns):
                    return s.ParameterizedTypePattern(
                        origin,
                        tuple(pattern for pattern in patterns if pattern is not None),
                    )

            case _:
                # Predicates and contextual expressions remain evaluator inputs.
                return None

        return None

    def _binary_predicate(
        self,
        value: object,
        origin: object,
        arguments: tuple[object, ...],
        selector_subject: s.Expression[RuntimeType] | None,
    ) -> s.EqualExpression[RuntimeType] | s.AssignableExpression[RuntimeType]:
        if len(arguments) == 1:
            if selector_subject is None:
                raise invalid(value, "Unary predicate requires a Map selector subject")

            try:
                target = normalize_selector_literal(arguments[0])
            except TypeError as error:
                raise invalid(value, str(error)) from error

            left, right = selector_subject, self._selection_type(self.adapt(target))
        elif len(arguments) == 2:
            left, right = (self._selection_type(self.adapt(arg)) for arg in arguments)
        else:
            raise invalid(value, "Binary predicates require two operands")

        if isinstance(left, s.KeyReference | s.FieldName) or isinstance(
            right, s.KeyReference | s.FieldName
        ):
            left, right = self._name_expression(left), self._name_expression(right)

        return (
            s.EqualExpression(left, right)
            if origin is Equal
            else s.AssignableExpression(left, right)
        )

    def _conditions(
        self,
        origin: object,
        arguments: tuple[object, ...],
        selector_subject: s.Expression[RuntimeType] | None,
    ) -> s.AllExpression[RuntimeType] | s.AnyExpression[RuntimeType]:
        conditions = tuple(
            self.adapt(arg, selector_subject=selector_subject) for arg in arguments
        )
        return (
            s.AllExpression(conditions)
            if origin is All
            else s.AnyExpression(conditions)
        )

    def _not(
        self,
        value: object,
        arguments: tuple[object, ...],
        selector_subject: s.Expression[RuntimeType] | None,
    ) -> s.NotExpression[RuntimeType]:
        if len(arguments) != 1:
            raise invalid(value, "Not requires one condition")

        return s.NotExpression(
            self.adapt(arguments[0], selector_subject=selector_subject)
        )

    def _annotated(
        self,
        arguments: tuple[object, ...],
        selector_subject: s.Expression[RuntimeType] | None,
    ) -> s.AnnotatedExpression[RuntimeType]:
        return s.AnnotatedExpression(
            concrete_type(Annotated),
            self.adapt(arguments[0], selector_subject=selector_subject),
            tuple(concrete_type(metadata) for metadata in arguments[1:]),
        )

    def _union(self, arguments: tuple[object, ...]) -> s.UnionExpression[RuntimeType]:
        return s.UnionExpression(tuple(self.adapt(arg) for arg in arguments))

    def _alias(
        self,
        value: object,
        alias: TypeAliasType,
        arguments: tuple[object, ...],
        selector_subject: s.Expression[RuntimeType] | None,
    ) -> s.Expression[RuntimeType]:
        if not _contains_operator(value):
            return self._ordinary_type(value, alias, arguments)

        child = self._alias_adapter(value, alias, arguments)
        return child.adapt(_alias_value(alias), selector_subject=selector_subject)

    def _alias_adapter(
        self,
        value: object,
        alias: TypeAliasType,
        arguments: tuple[object, ...],
        *,
        expand_arguments: bool = False,
    ) -> _AnnotationAdapter:
        if alias in self.aliases:
            raise SchemaIssue(
                "alias_cycle",
                "parsing",
                value,
                "recursive aliases used in Typeforge selection are not supported",
            )

        supplied = self._arguments(arguments)
        if expand_arguments:
            supplied = tuple(self._selection_type(item) for item in supplied)

        child = _AnnotationAdapter(
            origins=self.origins,
            bindings=dict(self.bindings),
            aliases=(*self.aliases, alias),
        )
        self._bind_alias(value, alias, supplied, child)
        return child

    def _bind_alias(
        self,
        value: object,
        alias: TypeAliasType,
        supplied: tuple[s.Expression[RuntimeType], ...],
        child: _AnnotationAdapter,
    ) -> None:
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
