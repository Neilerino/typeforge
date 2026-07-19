from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import singledispatch
from operator import getitem
from types import UnionType as PythonUnionType
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    LiteralString,
    Never,
    NotRequired,
    ReadOnly,
    Required,
    TypeAliasType,
    TypeVarTuple,
    Union,
    Unpack,
    assert_never,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from pydantic_core import CoreSchema, PydanticCustomError, core_schema
from pydantic_core.core_schema import SerializerFunctionWrapHandler
from returns.result import safe

from pydantic import GetCoreSchemaHandler, PydanticSchemaGenerationError
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
    If,
    Key,
    Map,
    MapFields,
    Not,
    OptionalField,
    ReadonlyField,
    Value,
)
from typeforge import (
    Any as AnyCondition,
)
from typeforge._documentation import Doc
from typeforge.utils.error_handling import ok


class SchemaErrorCode(StrEnum):
    ALIAS_CYCLE = "alias_cycle"
    ALIAS_ARGUMENTS = "alias_arguments"
    ASSIGNABILITY = "assignability"
    DUPLICATE_FIELD = "duplicate_field"
    EXPECTED_CONDITION = "expected_condition"
    EXPECTED_FIELD = "expected_field"
    EXPECTED_FIELD_NAME = "expected_field_name"
    EXPECTED_TYPE = "expected_type"
    INVALID_MARKER = "invalid_marker"
    MAP_NO_MATCH = "map_no_match"
    REBUILD_TYPE = "rebuild_type"
    UNSUPPORTED_RECORD = "unsupported_record"
    UNSUPPORTED_RELATIONSHIP = "unsupported_relationship"
    UNBOUND_INPUT = "unbound_input"
    UNBOUND_KEY = "unbound_key"
    UNBOUND_VALUE = "unbound_value"
    DEFAULT = "schema_base_error_inherit_me"


@dataclass(frozen=True)
class SchemaIssue(Exception):
    phase: str
    expression: str
    message: str
    code: ClassVar[SchemaErrorCode] = SchemaErrorCode.DEFAULT

    def render(self) -> str:
        return (
            f"Typeforge schema {self.phase} failed "
            f"[{self.code.value}] for {self.expression}: {self.message}"
        )


class AliasCycleError(SchemaIssue):
    code = SchemaErrorCode.ALIAS_CYCLE


class AliasArgumentsError(SchemaIssue):
    code = SchemaErrorCode.ALIAS_ARGUMENTS


class AssignabilityError(SchemaIssue):
    code = SchemaErrorCode.ASSIGNABILITY


class DuplicateFieldError(SchemaIssue):
    code = SchemaErrorCode.DUPLICATE_FIELD


class ExpectedConditionError(SchemaIssue):
    code = SchemaErrorCode.EXPECTED_CONDITION


class ExpectedFieldError(SchemaIssue):
    code = SchemaErrorCode.EXPECTED_FIELD


class ExpectedFieldNameError(SchemaIssue):
    code = SchemaErrorCode.EXPECTED_FIELD_NAME


class ExpectedTypeError(SchemaIssue):
    code = SchemaErrorCode.EXPECTED_TYPE


class InvalidMarkerError(SchemaIssue):
    code = SchemaErrorCode.INVALID_MARKER


class MapNoMatchError(SchemaIssue):
    code = SchemaErrorCode.MAP_NO_MATCH


class RebuildTypeError(SchemaIssue):
    code = SchemaErrorCode.REBUILD_TYPE


class UnsupportedRecordError(SchemaIssue):
    code = SchemaErrorCode.UNSUPPORTED_RECORD


class UnsupportedRelationshipError(SchemaIssue):
    code = SchemaErrorCode.UNSUPPORTED_RELATIONSHIP


class UnboundInputError(SchemaIssue):
    code = SchemaErrorCode.UNBOUND_INPUT


class UnboundKeyError(SchemaIssue):
    code = SchemaErrorCode.UNBOUND_KEY


class UnboundValueError(SchemaIssue):
    code = SchemaErrorCode.UNBOUND_VALUE


@dataclass(frozen=True, slots=True)
class ConcreteExpression:
    value: object


@dataclass(frozen=True, slots=True)
class ApplicationExpression:
    origin: object
    arguments: tuple[RuntimeExpression, ...]


@dataclass(frozen=True, slots=True)
class UnionExpression:
    members: tuple[RuntimeExpression, ...]


@dataclass(frozen=True, slots=True)
class LiteralExpression:
    values: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class AnnotatedExpression:
    value: RuntimeExpression
    metadata: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class InputExpression:
    pass


@dataclass(frozen=True, slots=True)
class KeyExpression:
    pass


@dataclass(frozen=True, slots=True)
class ValueExpression:
    pass


@dataclass(frozen=True, slots=True)
class DropExpression:
    pass


@dataclass(frozen=True, slots=True)
class EqualExpression:
    left: RuntimeExpression
    right: RuntimeExpression


@dataclass(frozen=True, slots=True)
class AssignableExpression:
    source: RuntimeExpression
    target: RuntimeExpression


@dataclass(frozen=True, slots=True)
class AllExpression:
    conditions: tuple[RuntimeExpression, ...]


@dataclass(frozen=True, slots=True)
class AnyExpression:
    conditions: tuple[RuntimeExpression, ...]


@dataclass(frozen=True, slots=True)
class NotExpression:
    condition: RuntimeExpression


@dataclass(frozen=True, slots=True)
class IfExpression:
    condition: RuntimeExpression
    when_true: RuntimeExpression
    when_false: RuntimeExpression


@dataclass(frozen=True, slots=True)
class CaseExpression:
    input_type: RuntimeExpression
    output_type: RuntimeExpression


@dataclass(frozen=True, slots=True)
class DefaultExpression:
    output_type: RuntimeExpression


@dataclass(frozen=True, slots=True)
class MapExpression:
    subject: RuntimeExpression
    cases: tuple[CaseExpression, ...]
    default: RuntimeExpression | None


@dataclass(frozen=True, slots=True)
class FieldExpression:
    name: RuntimeExpression
    value: RuntimeExpression


@dataclass(frozen=True, slots=True)
class OptionalFieldExpression:
    name: RuntimeExpression
    value: RuntimeExpression


@dataclass(frozen=True, slots=True)
class ReadonlyFieldExpression:
    name: RuntimeExpression
    value: RuntimeExpression


@dataclass(frozen=True, slots=True)
class MapFieldsExpression:
    record: RuntimeExpression
    transform: RuntimeExpression


@dataclass(frozen=True, slots=True)
class MalformedMarkerExpression:
    name: str
    message: str


@dataclass(frozen=True, slots=True)
class UnsupportedMarkerExpression:
    name: str


type RuntimeExpression = (
    ConcreteExpression
    | ApplicationExpression
    | UnionExpression
    | LiteralExpression
    | AnnotatedExpression
    | InputExpression
    | KeyExpression
    | ValueExpression
    | DropExpression
    | EqualExpression
    | AssignableExpression
    | AllExpression
    | AnyExpression
    | NotExpression
    | IfExpression
    | CaseExpression
    | DefaultExpression
    | MapExpression
    | FieldExpression
    | OptionalFieldExpression
    | ReadonlyFieldExpression
    | MapFieldsExpression
    | MalformedMarkerExpression
    | UnsupportedMarkerExpression
)


type _ExpressionFactory = Callable[..., RuntimeExpression]


def _fixed_arity(
    name: str,
    arguments: tuple[RuntimeExpression, ...],
    count: int,
    count_name: str,
    factory: _ExpressionFactory,
) -> RuntimeExpression:
    if len(arguments) != count:
        return MalformedMarkerExpression(
            name,
            f"{name} requires {count_name} arguments",
        )
    return factory(*arguments)


def _map_expression(arguments: tuple[RuntimeExpression, ...]) -> RuntimeExpression:
    if len(arguments) < 2:
        return MalformedMarkerExpression(
            "Map",
            "Map requires a subject and at least one Case or Default",
        )
    cases: list[CaseExpression] = []
    default: RuntimeExpression | None = None
    for entry in arguments[1:]:
        if isinstance(entry, CaseExpression):
            cases.append(entry)
            continue
        if isinstance(entry, DefaultExpression):
            if default is not None:
                return MalformedMarkerExpression(
                    "Map",
                    "Map may contain only one Default",
                )
            default = entry.output_type
            continue
        if isinstance(
            entry,
            ConcreteExpression
            | ApplicationExpression
            | UnionExpression
            | LiteralExpression
            | AnnotatedExpression
            | InputExpression,
        ):
            return MalformedMarkerExpression(
                "Map",
                "Map entries must be Case or Default",
            )
        return MalformedMarkerExpression(
            "Map",
            "Map entries must be Case[Input, Output] or Default[Output]",
        )
    return MapExpression(arguments[0], tuple(cases), default)


_MARKER_FACTORIES: dict[
    object, Callable[[tuple[RuntimeExpression, ...]], RuntimeExpression]
] = {
    All: AllExpression,
    AnyCondition: AnyExpression,
    Assignable: lambda arguments: _fixed_arity(
        "Assignable", arguments, 2, "two", AssignableExpression
    ),
    Case: lambda arguments: _fixed_arity("Case", arguments, 2, "two", CaseExpression),
    Collect: lambda arguments: UnsupportedMarkerExpression("Collect"),
    Default: lambda arguments: _fixed_arity(
        "Default", arguments, 1, "one", DefaultExpression
    ),
    Drop: lambda arguments: _fixed_arity("Drop", arguments, 0, "no", DropExpression),
    Each: lambda arguments: UnsupportedMarkerExpression("Each"),
    Equal: lambda arguments: _fixed_arity(
        "Equal", arguments, 2, "two", EqualExpression
    ),
    Field: lambda arguments: _fixed_arity(
        "Field", arguments, 2, "two", FieldExpression
    ),
    If: lambda arguments: _fixed_arity("If", arguments, 3, "three", IfExpression),
    Key: lambda arguments: _fixed_arity("Key", arguments, 0, "no", KeyExpression),
    Map: _map_expression,
    MapFields: lambda arguments: _fixed_arity(
        "MapFields", arguments, 2, "two", MapFieldsExpression
    ),
    Not: lambda arguments: _fixed_arity("Not", arguments, 1, "one", NotExpression),
    OptionalField: lambda arguments: _fixed_arity(
        "OptionalField", arguments, 2, "two", OptionalFieldExpression
    ),
    ReadonlyField: lambda arguments: _fixed_arity(
        "ReadonlyField", arguments, 2, "two", ReadonlyFieldExpression
    ),
    Value: lambda arguments: _fixed_arity("Value", arguments, 0, "no", ValueExpression),
}


@dataclass(frozen=True, slots=True)
class ResolvedType:
    value: object
    documentation: str | None = None


@dataclass(frozen=True, slots=True)
class FieldNameValue:
    value: str


@dataclass(frozen=True, slots=True)
class RecordField:
    name: str
    value: EvaluatedType
    required: bool
    readonly: bool


@dataclass(frozen=True, slots=True)
class RecordShape:
    name: str
    fields: tuple[RecordField, ...]
    documentation: str | None = None


@dataclass(frozen=True, slots=True)
class DroppedValue:
    pass


@dataclass(frozen=True, slots=True)
class RuntimeCase:
    pattern: RuntimeExpression
    output: RuntimeExpression
    tag: str


@dataclass(frozen=True, slots=True)
class RuntimeMapPlan:
    cases: tuple[RuntimeCase, ...]
    default: RuntimeExpression | None
    context: EvaluationContext


@dataclass(frozen=True, slots=True)
class RuntimeIfPlan:
    condition: RuntimeExpression
    when_true: RuntimeExpression
    when_false: RuntimeExpression
    context: EvaluationContext


type EvaluatedType = ResolvedType | RecordShape | RuntimeMapPlan | RuntimeIfPlan
type EvaluationValue = (
    EvaluatedType | bool | FieldNameValue | RecordField | DroppedValue
)


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    key: str | None = None
    value: EvaluatedType | None = None
    capture: ResolvedType | None = None
    input_type: ResolvedType | None = None


_EMPTY_EVALUATION_CONTEXT = EvaluationContext()


type _Binding = RuntimeExpression | tuple[RuntimeExpression, ...]
type _Environment = tuple[tuple[object, _Binding], ...]


@dataclass(frozen=True, slots=True)
class _ParseContext:
    environment: _Environment = ()
    aliases: tuple[TypeAliasType, ...] = ()


@dataclass(frozen=True, slots=True)
class _SchemaMetadata:
    def __get_pydantic_core_schema__(
        self,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        try:
            parsed = ok(parse_runtime_expression(source_type))
            evaluated = ok(evaluate_runtime_expression(parsed))
            if isinstance(evaluated, RecordShape):
                evaluated = replace(evaluated, name=_schema_name(source_type))
            return ok(emit_core_schema(evaluated, handler, repr(source_type)))
        except SchemaIssue as issue:
            raise PydanticSchemaGenerationError(issue.render()) from issue


type Schema[T] = Annotated[T, _SchemaMetadata()]
type Input = object


@safe(exceptions=(SchemaIssue,))
def parse_runtime_expression(value: object) -> RuntimeExpression:
    return _parse(value, _ParseContext())


def _parse(
    value: object,
    context: _ParseContext,
) -> RuntimeExpression:
    bound = _lookup(context.environment, value)
    if bound is not None:
        if isinstance(bound, tuple):
            raise AliasArgumentsError(
                "parsing",
                repr(value),
                "a variadic type parameter must be unpacked",
            )
        return bound

    if value is Input:
        return InputExpression()

    origin = get_origin(value)
    alias = origin if isinstance(origin, TypeAliasType) else value
    marker_factory = _MARKER_FACTORIES.get(alias)
    if marker_factory is not None:
        return marker_factory(_parse_arguments(get_args(value), context))

    if isinstance(alias, TypeAliasType):
        try:
            alias_value = alias.__value__
        except NameError as error:
            raise AliasArgumentsError(
                "parsing",
                repr(value),
                f"could not resolve alias value: {error}",
            ) from error
        if alias in context.aliases:
            raise AliasCycleError(
                "parsing",
                repr(value),
                "recursive aliases are not supported by this integration yet",
            )
        if not _contains_typeforge_alias(alias_value, (alias,)):
            return ConcreteExpression(value)
        bindings = _bind_alias(alias, get_args(value), context)
        return _parse(
            alias_value,
            _ParseContext(
                (*context.environment, *bindings),
                (*context.aliases, alias),
            ),
        )

    if origin is Annotated:
        arguments = get_args(value)
        return AnnotatedExpression(_parse(arguments[0], context), arguments[1:])

    if origin in {Union, PythonUnionType}:
        return UnionExpression(_parse_arguments(get_args(value), context))

    if origin is Literal:
        return LiteralExpression(get_args(value))

    if origin is not None:
        return ApplicationExpression(origin, _parse_arguments(get_args(value), context))

    return ConcreteExpression(value)


def _parse_arguments(
    arguments: tuple[object, ...],
    context: _ParseContext,
) -> tuple[RuntimeExpression, ...]:
    parsed: list[RuntimeExpression] = []
    for argument in arguments:
        if get_origin(argument) is Unpack:
            unpacked = get_args(argument)
            if len(unpacked) != 1:
                raise AliasArgumentsError(
                    "parsing",
                    repr(argument),
                    "Unpack requires exactly one argument",
                )
            bound = _lookup(context.environment, unpacked[0])
            if not isinstance(bound, tuple):
                raise AliasArgumentsError(
                    "parsing",
                    repr(argument),
                    "Unpack did not refer to a bound variadic parameter",
                )
            parsed.extend(bound)
            continue
        parsed.append(_parse(argument, context))
    return tuple(parsed)


def _bind_alias(
    alias: TypeAliasType,
    arguments: tuple[object, ...],
    context: _ParseContext,
) -> _Environment:
    parameters = alias.__type_params__
    bindings: list[tuple[object, _Binding]] = []
    argument_index = 0
    for parameter_index, parameter in enumerate(parameters):
        if isinstance(parameter, TypeVarTuple):
            fixed_after = sum(
                not isinstance(candidate, TypeVarTuple)
                for candidate in parameters[parameter_index + 1 :]
            )
            variadic_end = len(arguments) - fixed_after
            if variadic_end < argument_index:
                raise AliasArgumentsError(
                    "parsing",
                    repr(alias),
                    "not enough arguments for generic alias",
                )
            variadic: list[RuntimeExpression] = []
            for argument in arguments[argument_index:variadic_end]:
                variadic.append(_parse(argument, context))
            bindings.append((parameter, tuple(variadic)))
            argument_index = variadic_end
            continue
        if argument_index >= len(arguments):
            raise AliasArgumentsError(
                "parsing",
                repr(alias),
                "not enough arguments for generic alias",
            )
        bindings.append((parameter, _parse(arguments[argument_index], context)))
        argument_index += 1
    if argument_index != len(arguments):
        raise AliasArgumentsError(
            "parsing",
            repr(alias),
            "too many arguments for generic alias",
        )
    return tuple(bindings)


def _lookup(environment: _Environment, key: object) -> _Binding | None:
    for candidate, value in reversed(environment):
        if candidate is key:
            return value
    return None


@singledispatch
@safe(exceptions=(SchemaIssue,))
def evaluate_runtime_expression(
    expression: RuntimeExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    raise UnsupportedRelationshipError(
        "evaluation",
        repr(expression),
        f"unsupported expression {type(expression).__name__}",
    )


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: ConcreteExpression | LiteralExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    if isinstance(expression, LiteralExpression):
        return ResolvedType(Literal[expression.values])
    return ResolvedType(expression.value)


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: InputExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    if context.input_type is None:
        raise UnboundInputError(
            "evaluation",
            "Input",
            "Input requires value-time schema evaluation",
        )
    return context.input_type


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: ApplicationExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    arguments: list[object] = []
    for argument in expression.arguments:
        value = _evaluate_type(argument, context)
        if not isinstance(value, ResolvedType):
            raise RebuildTypeError(
                "evaluation",
                repr(expression.origin),
                "synthesized records cannot be nested in a generic application yet",
            )
        arguments.append(value.value)
    return ResolvedType(_apply_type(expression.origin, tuple(arguments)))


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: UnionExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    members = tuple(_evaluate_type(member, context) for member in expression.members)
    if all(isinstance(member, ResolvedType) for member in members):
        values = tuple(
            member.value for member in members if isinstance(member, ResolvedType)
        )
        return ResolvedType(_union_type(values))
    raise RebuildTypeError(
        "evaluation",
        repr(expression),
        "unions containing synthesized records are not supported yet",
    )


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: AnnotatedExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    evaluated = _evaluate_type(expression.value, context)
    documentation = next(
        (item.documentation for item in expression.metadata if isinstance(item, Doc)),
        None,
    )
    if isinstance(evaluated, RecordShape):
        return replace(evaluated, documentation=documentation)
    if isinstance(evaluated, ResolvedType):
        metadata = tuple(
            item for item in expression.metadata if not isinstance(item, Doc)
        )
        resolved_value = (
            Annotated[evaluated.value, *metadata] if metadata else evaluated.value
        )
        return ResolvedType(resolved_value, documentation)
    return evaluated


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: KeyExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    if context.key is None:
        raise UnboundKeyError(
            "evaluation",
            "Key",
            "Key is only valid inside MapFields",
        )
    return FieldNameValue(context.key)


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: ValueExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    if context.capture is not None:
        return context.capture
    if context.value is not None:
        return context.value
    raise UnboundValueError(
        "evaluation",
        "Value",
        "Value requires MapFields or a structural Map case",
    )


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: DropExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    return DroppedValue()


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: EqualExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    return _equal_values(
        ok(evaluate_runtime_expression(expression.left, context)),
        ok(evaluate_runtime_expression(expression.right, context)),
    )


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: AssignableExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    return _assignable_values(
        ok(evaluate_runtime_expression(expression.source, context)),
        ok(evaluate_runtime_expression(expression.target, context)),
    )


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: AllExpression | AnyExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    for condition in expression.conditions:
        match expression, _evaluate_condition(condition, context):
            case AllExpression(), False:
                return False
            case AnyExpression(), True:
                return True
            case _:
                continue
    return isinstance(expression, AllExpression)


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: NotExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    return not _evaluate_condition(expression.condition, context)


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: IfExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    if _contains_input(expression.condition) and context.input_type is None:
        return RuntimeIfPlan(
            expression.condition,
            expression.when_true,
            expression.when_false,
            context,
        )
    branch = (
        expression.when_true
        if _evaluate_condition(expression.condition, context)
        else expression.when_false
    )
    return ok(evaluate_runtime_expression(branch, context))


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: CaseExpression | DefaultExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    name = "Case" if isinstance(expression, CaseExpression) else "Default"
    raise InvalidMarkerError(
        "evaluation",
        name,
        f"{name} is only valid inside Map",
    )


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: MalformedMarkerExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    raise InvalidMarkerError("evaluation", expression.name, expression.message)


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: UnsupportedMarkerExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    raise UnsupportedRelationshipError(
        "evaluation",
        expression.name,
        f"{expression.name} has no Pydantic model-field semantics",
    )


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: MapExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    cases = tuple(
        RuntimeCase(case.input_type, case.output_type, f"case-{index}")
        for index, case in enumerate(expression.cases)
    )
    if _contains_input(expression.subject) and context.input_type is None:
        return RuntimeMapPlan(cases, expression.default, context)
    subject_value = _evaluate_type(expression.subject, context)
    if not isinstance(subject_value, ResolvedType):
        raise ExpectedTypeError(
            "evaluation",
            "Map",
            "Map subject must resolve to a concrete type",
        )
    members = _union_members(subject_value.value)
    outputs: list[object] = []
    for member in members:
        output = _map_member(member, cases, expression.default, context)
        if not isinstance(output, ResolvedType):
            raise ExpectedTypeError(
                "evaluation",
                "Map",
                "Map output must resolve to a concrete type",
            )
        outputs.append(output.value)
    return ResolvedType(_union_type(tuple(outputs)))


def _map_member(
    subject: object,
    cases: tuple[RuntimeCase, ...],
    default: RuntimeExpression | None,
    context: EvaluationContext,
) -> EvaluatedType:
    for case in cases:
        matched, captured = _match_pattern(case.pattern, subject, None, context)
        if not matched:
            continue
        return _evaluate_type(
            case.output,
            replace(context, capture=captured),
        )
    if default is None:
        return ResolvedType(Never)
    return _evaluate_type(default, context)


def _match_pattern(
    pattern: RuntimeExpression,
    subject: object,
    capture: ResolvedType | None,
    context: EvaluationContext,
) -> tuple[bool, ResolvedType | None]:
    if isinstance(pattern, ValueExpression):
        candidate = ResolvedType(subject)
        if capture is not None and capture.value != subject:
            return False, capture
        return True, candidate
    if isinstance(pattern, AnnotatedExpression):
        return _match_pattern(pattern.value, subject, capture, context)
    if isinstance(pattern, ApplicationExpression):
        subject_origin = get_origin(subject)
        if subject_origin != pattern.origin:
            return False, capture
        subject_arguments = get_args(subject)
        if len(subject_arguments) != len(pattern.arguments):
            return False, capture
        current = capture
        for nested_pattern, nested_subject in zip(
            pattern.arguments, subject_arguments, strict=True
        ):
            did_match, current = _match_pattern(
                nested_pattern,
                nested_subject,
                current,
                context,
            )
            if not did_match:
                return False, current
        return True, current
    value = _evaluate_type(pattern, context)
    if not isinstance(value, ResolvedType):
        return False, capture
    return value.value == subject, capture


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: FieldExpression | OptionalFieldExpression | ReadonlyFieldExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    return RecordField(
        name=_field_name(ok(evaluate_runtime_expression(expression.name, context))),
        value=_evaluate_type(expression.value, context),
        required=not isinstance(expression, OptionalFieldExpression),
        readonly=isinstance(expression, ReadonlyFieldExpression),
    )


@evaluate_runtime_expression.register
@safe(exceptions=(SchemaIssue,))
def _(
    expression: MapFieldsExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> EvaluationValue:
    source = _evaluate_type(expression.record, context)
    if not isinstance(source, ResolvedType) or not is_typeddict(source.value):
        raise UnsupportedRecordError(
            "evaluation",
            "MapFields",
            "the Pydantic integration currently supports TypedDict records only",
        )
    shape = _typed_dict_shape(source.value)
    fields: list[RecordField] = []
    names: set[str] = set()
    for source_field in shape.fields:
        value = ok(
            evaluate_runtime_expression(
                expression.transform,
                replace(context, key=source_field.name, value=source_field.value),
            )
        )
        if isinstance(value, DroppedValue):
            continue
        if not isinstance(value, RecordField):
            raise ExpectedFieldError(
                "evaluation",
                "MapFields",
                "the transform must produce Field, OptionalField, "
                "ReadonlyField, or Drop",
            )
        if value.name in names:
            raise DuplicateFieldError(
                "evaluation",
                "MapFields",
                f"multiple source fields produce {value.name!r}",
            )
        names.add(value.name)
        fields.append(value)
    return RecordShape(f"Typeforge_{shape.name}", tuple(fields))


def _typed_dict_shape(value: object) -> RecordShape:
    if not isinstance(value, type):
        raise UnsupportedRecordError(
            "evaluation",
            repr(value),
            "TypedDict record did not resolve to a class",
        )
    try:
        annotations = get_type_hints(value, include_extras=True)
    except NameError as error:
        raise UnsupportedRecordError(
            "evaluation",
            value.__name__,
            f"could not resolve record annotations: {error}",
        ) from error
    required_keys: frozenset[str] = getattr(value, "__required_keys__", frozenset())
    fields: list[RecordField] = []
    for name, annotation in annotations.items():
        unwrapped, readonly = _unwrap_field_annotation(annotation)
        fields.append(
            RecordField(
                name,
                ResolvedType(unwrapped),
                name in required_keys,
                readonly,
            )
        )
    return RecordShape(value.__name__, tuple(fields))


def _unwrap_field_annotation(annotation: object) -> tuple[object, bool]:
    readonly = False
    current = annotation
    metadata: list[object] = []
    while True:
        origin = get_origin(current)
        arguments = get_args(current)
        if origin is Annotated and arguments:
            current = arguments[0]
            metadata.extend(arguments[1:])
            continue
        if origin in {Required, NotRequired} and arguments:
            current = arguments[0]
            continue
        if origin is ReadOnly and arguments:
            readonly = True
            current = arguments[0]
            continue
        value = Annotated[current, *metadata] if metadata else current
        return value, readonly


@singledispatch
@safe(exceptions=(SchemaIssue,))
def emit_core_schema(
    evaluated: EvaluationValue,
    handler: GetCoreSchemaHandler,
    expression: str,
) -> CoreSchema:
    raise ExpectedTypeError(
        "emission",
        expression,
        "the expression did not evaluate to a type schema",
    )


@emit_core_schema.register
@safe(exceptions=(SchemaIssue,))
def _(
    evaluated: ResolvedType,
    handler: GetCoreSchemaHandler,
    expression: str,
) -> CoreSchema:
    try:
        schema = handler.generate_schema(evaluated.value)
    except Exception as error:
        raise ExpectedTypeError("emission", expression, str(error)) from error
    if evaluated.documentation is not None:
        return _with_json_schema_updates(
            schema, {"description": evaluated.documentation}
        )
    return schema


@emit_core_schema.register
@safe(exceptions=(SchemaIssue,))
def _(
    evaluated: RecordShape,
    handler: GetCoreSchemaHandler,
    expression: str,
) -> CoreSchema:
    fields = {
        field.name: core_schema.typed_dict_field(
            ok(emit_core_schema(field.value, handler, expression)),
            required=field.required,
            metadata=(
                {"pydantic_js_updates": {"readOnly": True}} if field.readonly else None
            ),
        )
        for field in evaluated.fields
    }
    metadata: dict[str, Any] | None = None
    if evaluated.documentation is not None:
        metadata = {
            "pydantic_js_updates": {
                "description": evaluated.documentation,
            }
        }
    return core_schema.typed_dict_schema(
        fields,
        cls_name=evaluated.name,
        total=False,
        extra_behavior="ignore",
        ref=f"typeforge.{evaluated.name}",
        metadata=metadata,
    )


@emit_core_schema.register
@safe(exceptions=(SchemaIssue,))
def _(
    plan: RuntimeMapPlan,
    handler: GetCoreSchemaHandler,
    expression: str,
) -> CoreSchema:
    choices: dict[str, CoreSchema] = {}
    outputs: dict[str, EvaluatedType] = {}
    for case in plan.cases:
        if _contains_generic_runtime_pattern(case.pattern):
            raise UnsupportedRelationshipError(
                "planning",
                repr(case.pattern),
                "value-time generic Map patterns are not supported; "
                "match a concrete runtime type instead",
            )
        output = _evaluate_type(case.output, plan.context)
        choices[case.tag] = ok(emit_core_schema(output, handler, expression))
        outputs[case.tag] = output
    if plan.default is not None:
        default_output = _evaluate_type(plan.default, plan.context)
        choices["default"] = ok(emit_core_schema(default_output, handler, expression))
        outputs["default"] = default_output

    def select_input(value: object) -> str | None:
        value_type = type(value)
        for case in plan.cases:
            matched = _match_runtime_pattern(case.pattern, value_type, value)
            if matched:
                return case.tag
        return "default" if plan.default is not None else None

    return _dispatch_schema(
        choices,
        outputs,
        select_input,
        "typeforge_map_no_match",
        "Input did not match any Typeforge Map case",
    )


@emit_core_schema.register
@safe(exceptions=(SchemaIssue,))
def _(
    plan: RuntimeIfPlan,
    handler: GetCoreSchemaHandler,
    expression: str,
) -> CoreSchema:
    branches: dict[str, CoreSchema] = {}
    outputs: dict[str, EvaluatedType] = {}
    for tag, branch in (("true", plan.when_true), ("false", plan.when_false)):
        evaluated = _evaluate_type(branch, plan.context)
        branches[tag] = ok(emit_core_schema(evaluated, handler, expression))
        outputs[tag] = evaluated

    def select_input(value: object) -> str | None:
        try:
            condition = _evaluate_condition(
                plan.condition,
                replace(plan.context, input_type=ResolvedType(type(value))),
            )
        except SchemaIssue:
            return None
        return "true" if condition else "false"

    return _dispatch_schema(
        branches,
        outputs,
        select_input,
        "typeforge_if_condition",
        "Input condition could not be evaluated",
    )


_DISPATCH_TAG = "__typeforge_tag__"
_DISPATCH_VALUE = "__typeforge_value__"


def _dispatch_schema(
    choices: dict[str, CoreSchema],
    outputs: dict[str, EvaluatedType],
    select_input: Callable[[object], str | None],
    error_type: LiteralString,
    error_message: LiteralString,
) -> CoreSchema:
    wrapped_choices: dict[str, CoreSchema] = {
        tag: core_schema.no_info_after_validator_function(
            _unwrap_dispatch_value,
            core_schema.typed_dict_schema(
                {
                    _DISPATCH_TAG: core_schema.typed_dict_field(
                        core_schema.literal_schema([tag])
                    ),
                    _DISPATCH_VALUE: core_schema.typed_dict_field(schema),
                },
                extra_behavior="forbid",
            ),
        )
        for tag, schema in choices.items()
    }
    tagged = core_schema.tagged_union_schema(
        wrapped_choices,
        discriminator=_DISPATCH_TAG,
    )

    def tag_input(value: object) -> dict[str, object]:
        tag = select_input(value)
        if not isinstance(tag, str) or tag not in choices:
            raise PydanticCustomError(error_type, error_message)
        return {_DISPATCH_TAG: tag, _DISPATCH_VALUE: value}

    def serialize(
        value: object,
        handler: SerializerFunctionWrapHandler,
    ) -> object:
        tag = next(
            (
                candidate
                for candidate, output in outputs.items()
                if _evaluated_output_matches(output, value)
            ),
            next(iter(choices)),
        )
        serialized: object = handler({_DISPATCH_TAG: tag, _DISPATCH_VALUE: value})
        if isinstance(serialized, dict):
            return cast(dict[str, object], serialized)[_DISPATCH_VALUE]
        return serialized

    return core_schema.no_info_before_validator_function(
        tag_input,
        tagged,
        json_schema_input_schema=core_schema.any_schema(),
        serialization=core_schema.wrap_serializer_function_ser_schema(
            serialize,
            return_schema=core_schema.any_schema(),
        ),
    )


def _unwrap_dispatch_value(value: dict[str, object]) -> object:
    return value[_DISPATCH_VALUE]


def _evaluated_output_matches(output: EvaluatedType, value: object) -> bool:
    if isinstance(output, ResolvedType):
        return _runtime_type_matches(output.value, value, strict=True)
    if isinstance(output, RecordShape):
        return isinstance(value, dict)
    return False


def _with_json_schema_updates(
    schema: CoreSchema,
    updates: dict[str, object],
) -> CoreSchema:
    return core_schema.chain_schema(
        [schema],
        metadata={"pydantic_js_updates": updates},
    )


def _match_runtime_pattern(
    pattern: RuntimeExpression,
    value_type: type[object],
    value: object,
) -> bool:
    if isinstance(pattern, InputExpression):
        return True
    try:
        result = _evaluate_type(
            pattern,
            EvaluationContext(input_type=ResolvedType(value_type)),
        )
    except SchemaIssue:
        return False
    return isinstance(result, ResolvedType) and _runtime_type_matches(
        result.value, value, strict=True
    )


def _contains_generic_runtime_pattern(pattern: RuntimeExpression) -> bool:
    if isinstance(pattern, ApplicationExpression):
        return True
    if isinstance(pattern, AnnotatedExpression):
        return _contains_generic_runtime_pattern(pattern.value)
    return False


def _runtime_type_matches(
    expected: object,
    value: object,
    *,
    strict: bool = False,
) -> bool:
    origin = get_origin(expected)
    if origin is Annotated:
        arguments = get_args(expected)
        return bool(arguments) and _runtime_type_matches(
            arguments[0], value, strict=strict
        )
    if origin in {Union, PythonUnionType}:
        return any(
            _runtime_type_matches(member, value, strict=strict)
            for member in get_args(expected)
        )
    if origin is Literal:
        return value in get_args(expected)
    candidate = origin or expected
    if not isinstance(candidate, type):
        return False
    if strict:
        return type(value) is candidate
    return isinstance(value, candidate)


def _evaluate_type(
    expression: RuntimeExpression,
    context: EvaluationContext,
) -> EvaluatedType:
    value = ok(evaluate_runtime_expression(expression, context))
    if isinstance(value, ResolvedType | RecordShape | RuntimeMapPlan | RuntimeIfPlan):
        return value
    raise ExpectedTypeError(
        "evaluation",
        repr(expression),
        "expression must evaluate to a type",
    )


def _evaluate_condition(
    expression: RuntimeExpression,
    context: EvaluationContext,
) -> bool:
    value = ok(evaluate_runtime_expression(expression, context))
    if isinstance(value, bool):
        return value
    raise ExpectedConditionError(
        "evaluation",
        repr(expression),
        "expression must evaluate to a condition",
    )


def _equal_values(
    left: EvaluationValue,
    right: EvaluationValue,
) -> bool:
    left_field = _as_field_name(left)
    right_field = _as_field_name(right)
    if left_field is not None or right_field is not None:
        return left_field is not None and left_field == right_field
    if isinstance(left, ResolvedType) and isinstance(right, ResolvedType):
        return left.value == right.value
    raise ExpectedTypeError(
        "evaluation",
        "Equal",
        "Equal operands must both be types or field names",
    )


def _assignable_values(
    source: EvaluationValue,
    target: EvaluationValue,
) -> bool:
    if not isinstance(source, ResolvedType) or not isinstance(target, ResolvedType):
        raise AssignabilityError(
            "evaluation",
            "Assignable",
            "Assignable operands must resolve to concrete types",
        )
    return _is_assignable(source.value, target.value)


def _is_assignable(source: object, target: object) -> bool:
    if source is Never:
        return True
    if target is Any or target is object:
        return True
    source_members = _union_members(source)
    target_members = _union_members(target)
    if len(source_members) > 1:
        return all(_is_assignable(member, target) for member in source_members)
    if len(target_members) > 1:
        return any(_is_assignable(source, member) for member in target_members)
    source_origin = get_origin(source)
    target_origin = get_origin(target)
    if source_origin is Literal:
        literal_values = cast(tuple[object, ...], get_args(source))
        return all(_is_assignable(type(value), target) for value in literal_values)
    if target_origin is Literal:
        return source == target
    source_class = source_origin or source
    target_class = target_origin or target
    if isinstance(source_class, type) and isinstance(target_class, type):
        try:
            if not issubclass(
                cast(type[object], source_class), cast(type[object], target_class)
            ):
                return False
        except TypeError:
            return False
        if source_origin == target_origin and get_args(target):
            return get_args(source) == get_args(target)
        return True
    return source == target


def _field_name(value: EvaluationValue) -> str:
    name = _as_field_name(value)
    if name is None:
        raise ExpectedFieldNameError(
            "evaluation",
            "Field",
            "field name must be Key or a single string Literal",
        )
    return name


def _as_field_name(value: EvaluationValue) -> str | None:
    if isinstance(value, FieldNameValue):
        return value.value
    if not isinstance(value, ResolvedType):
        return None
    if get_origin(value.value) is not Literal:
        return None
    arguments = get_args(value.value)
    if len(arguments) == 1 and isinstance(arguments[0], str):
        return arguments[0]
    return None


def _apply_type(
    origin: object,
    arguments: tuple[object, ...],
) -> object:
    try:
        if origin is PythonUnionType:
            return _union_type(arguments)
        subscription = arguments[0] if len(arguments) == 1 else arguments
        return getitem(cast(Any, origin), subscription)
    except (TypeError, ValueError) as error:
        raise RebuildTypeError(
            "evaluation",
            repr(origin),
            f"could not apply type arguments: {error}",
        ) from error


def _union_members(value: object) -> tuple[object, ...]:
    origin = get_origin(value)
    return get_args(value) if origin in {Union, PythonUnionType} else (value,)


def _union_type(members: tuple[object, ...]) -> object:
    unique: list[object] = []
    for member in members:
        if member is Never or member in unique:
            continue
        unique.append(member)
    if not unique:
        return Never
    if len(unique) == 1:
        return unique[0]
    return getitem(cast(Any, Union), tuple(unique))


def _contains_input(expression: RuntimeExpression) -> bool:
    match expression:
        case InputExpression():
            return True
        case (
            ConcreteExpression()
            | LiteralExpression()
            | KeyExpression()
            | ValueExpression()
            | DropExpression()
            | MalformedMarkerExpression()
            | UnsupportedMarkerExpression()
        ):
            return False
        case ApplicationExpression(_, arguments):
            return any(_contains_input(argument) for argument in arguments)
        case UnionExpression(members):
            return any(_contains_input(member) for member in members)
        case AnnotatedExpression(value):
            return _contains_input(value)
        case EqualExpression(left, right) | AssignableExpression(left, right):
            return _contains_input(left) or _contains_input(right)
        case AllExpression(conditions) | AnyExpression(conditions):
            return any(_contains_input(condition) for condition in conditions)
        case NotExpression(condition):
            return _contains_input(condition)
        case IfExpression(condition, when_true, when_false):
            return any(
                _contains_input(item) for item in (condition, when_true, when_false)
            )
        case CaseExpression(input_type, output_type):
            return _contains_input(input_type) or _contains_input(output_type)
        case DefaultExpression(output_type):
            return _contains_input(output_type)
        case MapExpression(subject, cases, default):
            return (
                _contains_input(subject)
                or any(_contains_input(case) for case in cases)
                or (default is not None and _contains_input(default))
            )
        case (
            FieldExpression(name, value)
            | OptionalFieldExpression(name, value)
            | ReadonlyFieldExpression(name, value)
        ):
            return _contains_input(name) or _contains_input(value)
        case MapFieldsExpression(record, transform):
            return _contains_input(record) or _contains_input(transform)
        case _ as unsupported:
            assert_never(unsupported)


def _contains_typeforge_alias(
    value: object,
    aliases: tuple[TypeAliasType, ...],
) -> bool:
    origin = get_origin(value)
    alias = origin if isinstance(origin, TypeAliasType) else value
    if alias in _MARKER_FACTORIES or alias is Input:
        return True
    if isinstance(alias, TypeAliasType):
        if alias in aliases:
            return False
        try:
            return _contains_typeforge_alias(alias.__value__, (*aliases, alias))
        except NameError:
            return False
    return any(
        _contains_typeforge_alias(argument, aliases) for argument in get_args(value)
    )


def _schema_name(value: object) -> str:
    origin = get_origin(value)
    base = origin if isinstance(origin, TypeAliasType) else value
    candidate: object = getattr(base, "__qualname__", None)
    if not isinstance(candidate, str):
        candidate = getattr(base, "__name__", None)
    fallback: object = getattr(type(base), "__name__", None)
    name = (
        candidate
        if isinstance(candidate, str)
        else fallback
        if isinstance(fallback, str)
        else "schema"
    )
    module: object = getattr(base, "__module__", None)
    if isinstance(module, str):
        name = f"{module}.{name}"
    arguments = get_args(value)
    if arguments:
        name = "_".join((name, *(_schema_name(item) for item in arguments)))
    return "".join(character if character.isalnum() else "_" for character in name)


__all__ = [
    "Input",
    "Schema",
    "SchemaErrorCode",
    "SchemaIssue",
    "emit_core_schema",
    "evaluate_runtime_expression",
    "parse_runtime_expression",
]
