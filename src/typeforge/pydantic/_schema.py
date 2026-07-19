from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from operator import getitem
from types import UnionType as PythonUnionType
from typing import (
    Annotated,
    Any,
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
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from pydantic_core import CoreSchema, PydanticCustomError, core_schema
from pydantic_core.core_schema import SerializerFunctionWrapHandler
from returns.result import Failure, Result, Success

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


class _MarkerKind(StrEnum):
    ALL = "All"
    ANY = "Any"
    ASSIGNABLE = "Assignable"
    CASE = "Case"
    COLLECT = "Collect"
    DEFAULT = "Default"
    DROP = "Drop"
    EACH = "Each"
    EQUAL = "Equal"
    FIELD = "Field"
    IF = "If"
    KEY = "Key"
    MAP = "Map"
    MAP_FIELDS = "MapFields"
    NOT = "Not"
    OPTIONAL_FIELD = "OptionalField"
    READONLY_FIELD = "ReadonlyField"
    VALUE = "Value"


_MARKERS: dict[object, _MarkerKind] = {
    All: _MarkerKind.ALL,
    AnyCondition: _MarkerKind.ANY,
    Assignable: _MarkerKind.ASSIGNABLE,
    Case: _MarkerKind.CASE,
    Collect: _MarkerKind.COLLECT,
    Default: _MarkerKind.DEFAULT,
    Drop: _MarkerKind.DROP,
    Each: _MarkerKind.EACH,
    Equal: _MarkerKind.EQUAL,
    Field: _MarkerKind.FIELD,
    If: _MarkerKind.IF,
    Key: _MarkerKind.KEY,
    Map: _MarkerKind.MAP,
    MapFields: _MarkerKind.MAP_FIELDS,
    Not: _MarkerKind.NOT,
    OptionalField: _MarkerKind.OPTIONAL_FIELD,
    ReadonlyField: _MarkerKind.READONLY_FIELD,
    Value: _MarkerKind.VALUE,
}


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


@dataclass(frozen=True, slots=True)
class SchemaIssue:
    code: SchemaErrorCode
    phase: str
    expression: str
    message: str

    def render(self) -> str:
        return (
            f"Typeforge schema {self.phase} failed "
            f"[{self.code.value}] for {self.expression}: {self.message}"
        )


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
class MarkerExpression:
    marker: _MarkerKind
    arguments: tuple[RuntimeExpression, ...]


@dataclass(frozen=True, slots=True)
class InputExpression:
    pass


type RuntimeExpression = (
    ConcreteExpression
    | ApplicationExpression
    | UnionExpression
    | LiteralExpression
    | AnnotatedExpression
    | MarkerExpression
    | InputExpression
)


@dataclass(frozen=True, slots=True)
class ResolvedType:
    value: object
    documentation: str | None = None


@dataclass(frozen=True, slots=True)
class ConditionValue:
    value: bool


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
class FieldValue:
    field: RecordField


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
    EvaluatedType | ConditionValue | FieldNameValue | FieldValue | DroppedValue
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
        parsed = parse_runtime_expression(source_type)
        if isinstance(parsed, Failure):
            raise PydanticSchemaGenerationError(parsed.failure().render())
        evaluated = evaluate_runtime_expression(parsed.unwrap())
        if isinstance(evaluated, Failure):
            raise PydanticSchemaGenerationError(evaluated.failure().render())
        evaluated_value = evaluated.unwrap()
        if isinstance(evaluated_value, RecordShape):
            evaluated_value = replace(
                evaluated_value,
                name=_schema_name(source_type),
            )
        emitted = emit_core_schema(evaluated_value, handler, repr(source_type))
        if isinstance(emitted, Failure):
            raise PydanticSchemaGenerationError(emitted.failure().render())
        return emitted.unwrap()


type Schema[T] = Annotated[T, _SchemaMetadata()]
type Input = object


def parse_runtime_expression(
    value: object,
) -> Result[RuntimeExpression, SchemaIssue]:
    return _parse(value, _ParseContext())


def _parse(
    value: object,
    context: _ParseContext,
) -> Result[RuntimeExpression, SchemaIssue]:
    bound = _lookup(context.environment, value)
    if bound is not None:
        if isinstance(bound, tuple):
            return _issue(
                SchemaErrorCode.ALIAS_ARGUMENTS,
                "parsing",
                repr(value),
                "a variadic type parameter must be unpacked",
            )
        return Success(bound)

    if value is Input:
        return Success(InputExpression())

    origin = get_origin(value)
    alias = origin if isinstance(origin, TypeAliasType) else value
    marker = _MARKERS.get(alias)
    if marker is not None:
        arguments = get_args(value)
        parsed_arguments = _parse_arguments(arguments, context)
        if isinstance(parsed_arguments, Failure):
            return parsed_arguments
        return Success(MarkerExpression(marker, parsed_arguments.unwrap()))

    if isinstance(alias, TypeAliasType):
        try:
            alias_value = alias.__value__
        except NameError as error:
            return _issue(
                SchemaErrorCode.ALIAS_ARGUMENTS,
                "parsing",
                repr(value),
                f"could not resolve alias value: {error}",
            )
        if alias in context.aliases:
            return _issue(
                SchemaErrorCode.ALIAS_CYCLE,
                "parsing",
                repr(value),
                "recursive aliases are not supported by this integration yet",
            )
        if not _contains_typeforge_alias(alias_value, (alias,)):
            return Success(ConcreteExpression(value))
        bindings = _bind_alias(alias, get_args(value), context)
        if isinstance(bindings, Failure):
            return bindings
        return _parse(
            alias_value,
            _ParseContext(
                (*context.environment, *bindings.unwrap()),
                (*context.aliases, alias),
            ),
        )

    if origin is Annotated:
        arguments = get_args(value)
        parsed_value = _parse(arguments[0], context)
        if isinstance(parsed_value, Failure):
            return parsed_value
        return Success(AnnotatedExpression(parsed_value.unwrap(), arguments[1:]))

    if origin in {Union, PythonUnionType}:
        members = _parse_arguments(get_args(value), context)
        if isinstance(members, Failure):
            return members
        return Success(UnionExpression(members.unwrap()))

    if origin is Literal:
        return Success(LiteralExpression(get_args(value)))

    if origin is not None:
        parsed_arguments = _parse_arguments(get_args(value), context)
        if isinstance(parsed_arguments, Failure):
            return parsed_arguments
        return Success(ApplicationExpression(origin, parsed_arguments.unwrap()))

    return Success(ConcreteExpression(value))


def _parse_arguments(
    arguments: tuple[object, ...],
    context: _ParseContext,
) -> Result[tuple[RuntimeExpression, ...], SchemaIssue]:
    parsed: list[RuntimeExpression] = []
    for argument in arguments:
        if get_origin(argument) is Unpack:
            unpacked = get_args(argument)
            if len(unpacked) != 1:
                return _issue(
                    SchemaErrorCode.ALIAS_ARGUMENTS,
                    "parsing",
                    repr(argument),
                    "Unpack requires exactly one argument",
                )
            bound = _lookup(context.environment, unpacked[0])
            if not isinstance(bound, tuple):
                return _issue(
                    SchemaErrorCode.ALIAS_ARGUMENTS,
                    "parsing",
                    repr(argument),
                    "Unpack did not refer to a bound variadic parameter",
                )
            parsed.extend(bound)
            continue
        item = _parse(argument, context)
        if isinstance(item, Failure):
            return item
        parsed.append(item.unwrap())
    return Success(tuple(parsed))


def _bind_alias(
    alias: TypeAliasType,
    arguments: tuple[object, ...],
    context: _ParseContext,
) -> Result[_Environment, SchemaIssue]:
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
                return _issue(
                    SchemaErrorCode.ALIAS_ARGUMENTS,
                    "parsing",
                    repr(alias),
                    "not enough arguments for generic alias",
                )
            variadic: list[RuntimeExpression] = []
            for argument in arguments[argument_index:variadic_end]:
                parsed = _parse(argument, context)
                if isinstance(parsed, Failure):
                    return parsed
                variadic.append(parsed.unwrap())
            bindings.append((parameter, tuple(variadic)))
            argument_index = variadic_end
            continue
        if argument_index >= len(arguments):
            return _issue(
                SchemaErrorCode.ALIAS_ARGUMENTS,
                "parsing",
                repr(alias),
                "not enough arguments for generic alias",
            )
        parsed = _parse(arguments[argument_index], context)
        if isinstance(parsed, Failure):
            return parsed
        bindings.append((parameter, parsed.unwrap()))
        argument_index += 1
    if argument_index != len(arguments):
        return _issue(
            SchemaErrorCode.ALIAS_ARGUMENTS,
            "parsing",
            repr(alias),
            "too many arguments for generic alias",
        )
    return Success(tuple(bindings))


def _lookup(environment: _Environment, key: object) -> _Binding | None:
    for candidate, value in reversed(environment):
        if candidate is key:
            return value
    return None


def evaluate_runtime_expression(
    expression: RuntimeExpression,
    context: EvaluationContext = _EMPTY_EVALUATION_CONTEXT,
) -> Result[EvaluationValue, SchemaIssue]:
    if isinstance(expression, ConcreteExpression):
        return Success(ResolvedType(expression.value))
    if isinstance(expression, LiteralExpression):
        return Success(ResolvedType(Literal[expression.values]))
    if isinstance(expression, UnionExpression):
        return _evaluate_union(expression, context)
    if isinstance(expression, ApplicationExpression):
        return _evaluate_application(expression, context)
    if isinstance(expression, AnnotatedExpression):
        return _evaluate_annotated(expression, context)
    if isinstance(expression, InputExpression):
        if context.input_type is None:
            return _issue(
                SchemaErrorCode.UNBOUND_INPUT,
                "evaluation",
                "Input",
                "Input requires value-time schema evaluation",
            )
        return Success(context.input_type)
    return _evaluate_marker(expression, context)


def _evaluate_application(
    expression: ApplicationExpression,
    context: EvaluationContext,
) -> Result[EvaluationValue, SchemaIssue]:
    arguments: list[object] = []
    for argument in expression.arguments:
        evaluated = _evaluate_type(argument, context)
        if isinstance(evaluated, Failure):
            return evaluated
        value = evaluated.unwrap()
        if not isinstance(value, ResolvedType):
            return _issue(
                SchemaErrorCode.REBUILD_TYPE,
                "evaluation",
                repr(expression.origin),
                "synthesized records cannot be nested in a generic application yet",
            )
        arguments.append(value.value)
    rebuilt = _apply_type(expression.origin, tuple(arguments))
    if isinstance(rebuilt, Failure):
        return rebuilt
    return Success(ResolvedType(rebuilt.unwrap()))


def _evaluate_union(
    expression: UnionExpression,
    context: EvaluationContext,
) -> Result[EvaluationValue, SchemaIssue]:
    members: list[EvaluatedType] = []
    for member in expression.members:
        evaluated = _evaluate_type(member, context)
        if isinstance(evaluated, Failure):
            return evaluated
        members.append(evaluated.unwrap())
    if all(isinstance(member, ResolvedType) for member in members):
        values = tuple(
            member.value for member in members if isinstance(member, ResolvedType)
        )
        return Success(ResolvedType(_union_type(values)))
    return _issue(
        SchemaErrorCode.REBUILD_TYPE,
        "evaluation",
        repr(expression),
        "unions containing synthesized records are not supported yet",
    )


def _evaluate_annotated(
    expression: AnnotatedExpression,
    context: EvaluationContext,
) -> Result[EvaluationValue, SchemaIssue]:
    evaluated_result = _evaluate_type(expression.value, context)
    if isinstance(evaluated_result, Failure):
        return evaluated_result
    evaluated = evaluated_result.unwrap()
    documentation = next(
        (item.documentation for item in expression.metadata if isinstance(item, Doc)),
        None,
    )
    if isinstance(evaluated, RecordShape):
        return Success(replace(evaluated, documentation=documentation))
    if isinstance(evaluated, ResolvedType):
        metadata = tuple(
            item for item in expression.metadata if not isinstance(item, Doc)
        )
        resolved_value = (
            Annotated[evaluated.value, *metadata] if metadata else evaluated.value
        )
        return Success(ResolvedType(resolved_value, documentation))
    return Success(evaluated)


def _evaluate_marker(
    expression: MarkerExpression,
    context: EvaluationContext,
) -> Result[EvaluationValue, SchemaIssue]:
    marker = expression.marker
    arguments = expression.arguments
    if marker is _MarkerKind.KEY:
        if arguments:
            return _marker_arity(expression, "no")
        if context.key is None:
            return _issue(
                SchemaErrorCode.UNBOUND_KEY,
                "evaluation",
                "Key",
                "Key is only valid inside MapFields",
            )
        return Success(FieldNameValue(context.key))
    if marker is _MarkerKind.VALUE:
        if arguments:
            return _marker_arity(expression, "no")
        if context.capture is not None:
            return Success(context.capture)
        if context.value is not None:
            return Success(context.value)
        return _issue(
            SchemaErrorCode.UNBOUND_VALUE,
            "evaluation",
            "Value",
            "Value requires MapFields or a structural Map case",
        )
    if marker is _MarkerKind.DROP:
        if arguments:
            return _marker_arity(expression, "no")
        return Success(DroppedValue())
    if marker in {_MarkerKind.EQUAL, _MarkerKind.ASSIGNABLE}:
        if len(arguments) != 2:
            return _marker_arity(expression, "two")
        left = evaluate_runtime_expression(arguments[0], context)
        if isinstance(left, Failure):
            return left
        right = evaluate_runtime_expression(arguments[1], context)
        if isinstance(right, Failure):
            return right
        if marker is _MarkerKind.EQUAL:
            equal = _equal_values(left.unwrap(), right.unwrap())
            if isinstance(equal, Failure):
                return equal
            return Success(ConditionValue(equal.unwrap()))
        assignable = _assignable_values(left.unwrap(), right.unwrap())
        if isinstance(assignable, Failure):
            return assignable
        return Success(ConditionValue(assignable.unwrap()))
    if marker in {_MarkerKind.ALL, _MarkerKind.ANY}:
        values: list[bool] = []
        for argument in arguments:
            condition = _evaluate_condition(argument, context)
            if isinstance(condition, Failure):
                return condition
            values.append(condition.unwrap())
        return Success(
            ConditionValue(all(values) if marker is _MarkerKind.ALL else any(values))
        )
    if marker is _MarkerKind.NOT:
        if len(arguments) != 1:
            return _marker_arity(expression, "one")
        condition = _evaluate_condition(arguments[0], context)
        if isinstance(condition, Failure):
            return condition
        return Success(ConditionValue(not condition.unwrap()))
    if marker is _MarkerKind.IF:
        if len(arguments) != 3:
            return _marker_arity(expression, "three")
        if _contains_input(arguments[0]) and context.input_type is None:
            return Success(RuntimeIfPlan(*arguments, context))
        condition = _evaluate_condition(arguments[0], context)
        if isinstance(condition, Failure):
            return condition
        branch = arguments[1] if condition.unwrap() else arguments[2]
        return evaluate_runtime_expression(branch, context)
    if marker is _MarkerKind.MAP:
        return _evaluate_map(arguments, context)
    if marker in {
        _MarkerKind.FIELD,
        _MarkerKind.OPTIONAL_FIELD,
        _MarkerKind.READONLY_FIELD,
    }:
        return _evaluate_field(marker, arguments, context)
    if marker is _MarkerKind.MAP_FIELDS:
        return _evaluate_map_fields(arguments, context)
    if marker in {_MarkerKind.CASE, _MarkerKind.DEFAULT}:
        return _issue(
            SchemaErrorCode.INVALID_MARKER,
            "evaluation",
            marker.value,
            f"{marker.value} is only valid inside Map",
        )
    return _issue(
        SchemaErrorCode.UNSUPPORTED_RELATIONSHIP,
        "evaluation",
        marker.value,
        f"{marker.value} has no Pydantic model-field semantics",
    )


def _evaluate_map(
    arguments: tuple[RuntimeExpression, ...],
    context: EvaluationContext,
) -> Result[EvaluationValue, SchemaIssue]:
    if len(arguments) < 2:
        return _issue(
            SchemaErrorCode.INVALID_MARKER,
            "evaluation",
            "Map",
            "Map requires a subject and at least one Case or Default",
        )
    cases_result = _map_entries(arguments[1:])
    if isinstance(cases_result, Failure):
        return cases_result
    cases, default = cases_result.unwrap()
    if _contains_input(arguments[0]) and context.input_type is None:
        return Success(RuntimeMapPlan(cases, default, context))
    subject = _evaluate_type(arguments[0], context)
    if isinstance(subject, Failure):
        return subject
    subject_value = subject.unwrap()
    if not isinstance(subject_value, ResolvedType):
        return _issue(
            SchemaErrorCode.EXPECTED_TYPE,
            "evaluation",
            "Map",
            "Map subject must resolve to a concrete type",
        )
    members = _union_members(subject_value.value)
    outputs: list[object] = []
    for member in members:
        matched = _map_member(member, cases, default, context)
        if isinstance(matched, Failure):
            return matched
        output = matched.unwrap()
        if not isinstance(output, ResolvedType):
            return _issue(
                SchemaErrorCode.EXPECTED_TYPE,
                "evaluation",
                "Map",
                "Map output must resolve to a concrete type",
            )
        outputs.append(output.value)
    return Success(ResolvedType(_union_type(tuple(outputs))))


def _map_entries(
    entries: tuple[RuntimeExpression, ...],
) -> Result[tuple[tuple[RuntimeCase, ...], RuntimeExpression | None], SchemaIssue]:
    cases: list[RuntimeCase] = []
    default: RuntimeExpression | None = None
    for entry in entries:
        if not isinstance(entry, MarkerExpression):
            return _issue(
                SchemaErrorCode.INVALID_MARKER,
                "evaluation",
                "Map",
                "Map entries must be Case or Default",
            )
        if entry.marker is _MarkerKind.CASE and len(entry.arguments) == 2:
            cases.append(RuntimeCase(*entry.arguments, f"case-{len(cases)}"))
            continue
        if entry.marker is _MarkerKind.DEFAULT and len(entry.arguments) == 1:
            if default is not None:
                return _issue(
                    SchemaErrorCode.INVALID_MARKER,
                    "evaluation",
                    "Map",
                    "Map may contain only one Default",
                )
            default = entry.arguments[0]
            continue
        return _issue(
            SchemaErrorCode.INVALID_MARKER,
            "evaluation",
            "Map",
            "Map entries must be Case[Input, Output] or Default[Output]",
        )
    return Success((tuple(cases), default))


def _map_member(
    subject: object,
    cases: tuple[RuntimeCase, ...],
    default: RuntimeExpression | None,
    context: EvaluationContext,
) -> Result[EvaluatedType, SchemaIssue]:
    for case in cases:
        capture = _match_pattern(case.pattern, subject, None, context)
        if isinstance(capture, Failure):
            return capture
        matched, captured = capture.unwrap()
        if not matched:
            continue
        evaluated = _evaluate_type(
            case.output,
            replace(context, capture=captured),
        )
        return evaluated
    if default is None:
        return Success(ResolvedType(Never))
    return _evaluate_type(default, context)


def _match_pattern(
    pattern: RuntimeExpression,
    subject: object,
    capture: ResolvedType | None,
    context: EvaluationContext,
) -> Result[tuple[bool, ResolvedType | None], SchemaIssue]:
    if isinstance(pattern, MarkerExpression) and pattern.marker is _MarkerKind.VALUE:
        candidate = ResolvedType(subject)
        if capture is not None and capture.value != subject:
            return Success((False, capture))
        return Success((True, candidate))
    if isinstance(pattern, AnnotatedExpression):
        return _match_pattern(pattern.value, subject, capture, context)
    if isinstance(pattern, ApplicationExpression):
        subject_origin = get_origin(subject)
        if subject_origin != pattern.origin:
            return Success((False, capture))
        subject_arguments = get_args(subject)
        if len(subject_arguments) != len(pattern.arguments):
            return Success((False, capture))
        current = capture
        for nested_pattern, nested_subject in zip(
            pattern.arguments, subject_arguments, strict=True
        ):
            matched = _match_pattern(
                nested_pattern,
                nested_subject,
                current,
                context,
            )
            if isinstance(matched, Failure):
                return matched
            did_match, current = matched.unwrap()
            if not did_match:
                return Success((False, current))
        return Success((True, current))
    evaluated = _evaluate_type(pattern, context)
    if isinstance(evaluated, Failure):
        return evaluated
    value = evaluated.unwrap()
    if not isinstance(value, ResolvedType):
        return Success((False, capture))
    return Success((value.value == subject, capture))


def _evaluate_field(
    marker: _MarkerKind,
    arguments: tuple[RuntimeExpression, ...],
    context: EvaluationContext,
) -> Result[EvaluationValue, SchemaIssue]:
    if len(arguments) != 2:
        return _issue(
            SchemaErrorCode.INVALID_MARKER,
            "evaluation",
            marker.value,
            f"{marker.value} requires two arguments",
        )
    name = evaluate_runtime_expression(arguments[0], context)
    if isinstance(name, Failure):
        return name
    field_name = _field_name(name.unwrap())
    if isinstance(field_name, Failure):
        return field_name
    value = _evaluate_type(arguments[1], context)
    if isinstance(value, Failure):
        return value
    return Success(
        FieldValue(
            RecordField(
                name=field_name.unwrap(),
                value=value.unwrap(),
                required=marker is not _MarkerKind.OPTIONAL_FIELD,
                readonly=marker is _MarkerKind.READONLY_FIELD,
            )
        )
    )


def _evaluate_map_fields(
    arguments: tuple[RuntimeExpression, ...],
    context: EvaluationContext,
) -> Result[EvaluationValue, SchemaIssue]:
    if len(arguments) != 2:
        return _issue(
            SchemaErrorCode.INVALID_MARKER,
            "evaluation",
            "MapFields",
            "MapFields requires a record and transform",
        )
    record = _evaluate_type(arguments[0], context)
    if isinstance(record, Failure):
        return record
    source = record.unwrap()
    if not isinstance(source, ResolvedType) or not is_typeddict(source.value):
        return _issue(
            SchemaErrorCode.UNSUPPORTED_RECORD,
            "evaluation",
            "MapFields",
            "the Pydantic integration currently supports TypedDict records only",
        )
    shape = _typed_dict_shape(source.value)
    if isinstance(shape, Failure):
        return shape
    fields: list[RecordField] = []
    names: set[str] = set()
    for source_field in shape.unwrap().fields:
        transformed = evaluate_runtime_expression(
            arguments[1],
            replace(context, key=source_field.name, value=source_field.value),
        )
        if isinstance(transformed, Failure):
            return transformed
        value = transformed.unwrap()
        if isinstance(value, DroppedValue):
            continue
        if not isinstance(value, FieldValue):
            return _issue(
                SchemaErrorCode.EXPECTED_FIELD,
                "evaluation",
                "MapFields",
                "the transform must produce Field, OptionalField, "
                "ReadonlyField, or Drop",
            )
        if value.field.name in names:
            return _issue(
                SchemaErrorCode.DUPLICATE_FIELD,
                "evaluation",
                "MapFields",
                f"multiple source fields produce {value.field.name!r}",
            )
        names.add(value.field.name)
        fields.append(value.field)
    return Success(RecordShape(f"Typeforge_{shape.unwrap().name}", tuple(fields)))


def _typed_dict_shape(value: object) -> Result[RecordShape, SchemaIssue]:
    if not isinstance(value, type):
        return _issue(
            SchemaErrorCode.UNSUPPORTED_RECORD,
            "evaluation",
            repr(value),
            "TypedDict record did not resolve to a class",
        )
    try:
        annotations = get_type_hints(value, include_extras=True)
    except NameError as error:
        return _issue(
            SchemaErrorCode.UNSUPPORTED_RECORD,
            "evaluation",
            value.__name__,
            f"could not resolve record annotations: {error}",
        )
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
    return Success(RecordShape(value.__name__, tuple(fields)))


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


def emit_core_schema(
    evaluated: EvaluationValue,
    handler: GetCoreSchemaHandler,
    expression: str,
) -> Result[CoreSchema, SchemaIssue]:
    if isinstance(evaluated, ResolvedType):
        try:
            schema = handler.generate_schema(evaluated.value)
            if evaluated.documentation is not None:
                schema = _with_json_schema_updates(
                    schema, {"description": evaluated.documentation}
                )
            return Success(schema)
        except Exception as error:
            return _issue(
                SchemaErrorCode.EXPECTED_TYPE,
                "emission",
                expression,
                str(error),
            )
    if isinstance(evaluated, RecordShape):
        fields: dict[str, core_schema.TypedDictField] = {}
        for field in evaluated.fields:
            field_schema = emit_core_schema(field.value, handler, expression)
            if isinstance(field_schema, Failure):
                return field_schema
            fields[field.name] = core_schema.typed_dict_field(
                field_schema.unwrap(),
                required=field.required,
                metadata=(
                    {"pydantic_js_updates": {"readOnly": True}}
                    if field.readonly
                    else None
                ),
            )
        metadata: dict[str, Any] | None = None
        if evaluated.documentation is not None:
            metadata = {
                "pydantic_js_updates": {
                    "description": evaluated.documentation,
                }
            }
        return Success(
            core_schema.typed_dict_schema(
                fields,
                cls_name=evaluated.name,
                total=False,
                extra_behavior="ignore",
                ref=f"typeforge.{evaluated.name}",
                metadata=metadata,
            )
        )
    if isinstance(evaluated, RuntimeMapPlan):
        return _emit_runtime_map(evaluated, handler, expression)
    if isinstance(evaluated, RuntimeIfPlan):
        return _emit_runtime_if(evaluated, handler, expression)
    return _issue(
        SchemaErrorCode.EXPECTED_TYPE,
        "emission",
        expression,
        "the expression did not evaluate to a type schema",
    )


def _emit_runtime_map(
    plan: RuntimeMapPlan,
    handler: GetCoreSchemaHandler,
    expression: str,
) -> Result[CoreSchema, SchemaIssue]:
    choices: dict[str, CoreSchema] = {}
    outputs: dict[str, EvaluatedType] = {}
    for case in plan.cases:
        if _contains_generic_runtime_pattern(case.pattern):
            return _issue(
                SchemaErrorCode.UNSUPPORTED_RELATIONSHIP,
                "planning",
                repr(case.pattern),
                "value-time generic Map patterns are not supported; "
                "match a concrete runtime type instead",
            )
        output = _evaluate_type(case.output, plan.context)
        if isinstance(output, Failure):
            return output
        emitted = emit_core_schema(output.unwrap(), handler, expression)
        if isinstance(emitted, Failure):
            return emitted
        choices[case.tag] = emitted.unwrap()
        outputs[case.tag] = output.unwrap()
    if plan.default is not None:
        default_output = _evaluate_type(plan.default, plan.context)
        if isinstance(default_output, Failure):
            return default_output
        emitted_default = emit_core_schema(default_output.unwrap(), handler, expression)
        if isinstance(emitted_default, Failure):
            return emitted_default
        choices["default"] = emitted_default.unwrap()
        outputs["default"] = default_output.unwrap()

    def select_input(value: object) -> str | None:
        value_type = type(value)
        for case in plan.cases:
            matched = _match_runtime_pattern(case.pattern, value_type, value)
            if matched:
                return case.tag
        return "default" if plan.default is not None else None

    return Success(
        _dispatch_schema(
            choices,
            outputs,
            select_input,
            "typeforge_map_no_match",
            "Input did not match any Typeforge Map case",
        )
    )


def _emit_runtime_if(
    plan: RuntimeIfPlan,
    handler: GetCoreSchemaHandler,
    expression: str,
) -> Result[CoreSchema, SchemaIssue]:
    branches: dict[str, CoreSchema] = {}
    outputs: dict[str, EvaluatedType] = {}
    for tag, branch in (("true", plan.when_true), ("false", plan.when_false)):
        evaluated = _evaluate_type(branch, plan.context)
        if isinstance(evaluated, Failure):
            return evaluated
        emitted = emit_core_schema(evaluated.unwrap(), handler, expression)
        if isinstance(emitted, Failure):
            return emitted
        branches[tag] = emitted.unwrap()
        outputs[tag] = evaluated.unwrap()

    def select_input(value: object) -> str | None:
        condition = _evaluate_condition(
            plan.condition,
            replace(plan.context, input_type=ResolvedType(type(value))),
        )
        if isinstance(condition, Success):
            return "true" if condition.unwrap() else "false"
        return None

    return Success(
        _dispatch_schema(
            branches,
            outputs,
            select_input,
            "typeforge_if_condition",
            "Input condition could not be evaluated",
        )
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
    evaluated = _evaluate_type(
        pattern,
        EvaluationContext(input_type=ResolvedType(value_type)),
    )
    if isinstance(evaluated, Failure):
        return False
    result = evaluated.unwrap()
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
) -> Result[EvaluatedType, SchemaIssue]:
    evaluated = evaluate_runtime_expression(expression, context)
    if isinstance(evaluated, Failure):
        return evaluated
    value = evaluated.unwrap()
    if isinstance(value, ResolvedType | RecordShape | RuntimeMapPlan | RuntimeIfPlan):
        return Success(value)
    return _issue(
        SchemaErrorCode.EXPECTED_TYPE,
        "evaluation",
        repr(expression),
        "expression must evaluate to a type",
    )


def _evaluate_condition(
    expression: RuntimeExpression,
    context: EvaluationContext,
) -> Result[bool, SchemaIssue]:
    evaluated = evaluate_runtime_expression(expression, context)
    if isinstance(evaluated, Failure):
        return evaluated
    value = evaluated.unwrap()
    if isinstance(value, ConditionValue):
        return Success(value.value)
    return _issue(
        SchemaErrorCode.EXPECTED_CONDITION,
        "evaluation",
        repr(expression),
        "expression must evaluate to a condition",
    )


def _equal_values(
    left: EvaluationValue,
    right: EvaluationValue,
) -> Result[bool, SchemaIssue]:
    left_field = _as_field_name(left)
    right_field = _as_field_name(right)
    if left_field is not None or right_field is not None:
        return Success(left_field is not None and left_field == right_field)
    if isinstance(left, ResolvedType) and isinstance(right, ResolvedType):
        return Success(left.value == right.value)
    return _issue(
        SchemaErrorCode.EXPECTED_TYPE,
        "evaluation",
        "Equal",
        "Equal operands must both be types or field names",
    )


def _assignable_values(
    source: EvaluationValue,
    target: EvaluationValue,
) -> Result[bool, SchemaIssue]:
    if not isinstance(source, ResolvedType) or not isinstance(target, ResolvedType):
        return _issue(
            SchemaErrorCode.ASSIGNABILITY,
            "evaluation",
            "Assignable",
            "Assignable operands must resolve to concrete types",
        )
    return Success(_is_assignable(source.value, target.value))


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


def _field_name(value: EvaluationValue) -> Result[str, SchemaIssue]:
    name = _as_field_name(value)
    if name is None:
        return _issue(
            SchemaErrorCode.EXPECTED_FIELD_NAME,
            "evaluation",
            "Field",
            "field name must be Key or a single string Literal",
        )
    return Success(name)


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
) -> Result[object, SchemaIssue]:
    try:
        if origin is PythonUnionType:
            return Success(_union_type(arguments))
        subscription = arguments[0] if len(arguments) == 1 else arguments
        return Success(getitem(cast(Any, origin), subscription))
    except (TypeError, ValueError) as error:
        return _issue(
            SchemaErrorCode.REBUILD_TYPE,
            "evaluation",
            repr(origin),
            f"could not apply type arguments: {error}",
        )


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
    if isinstance(expression, InputExpression):
        return True
    if isinstance(expression, MarkerExpression | ApplicationExpression):
        return any(_contains_input(argument) for argument in expression.arguments)
    if isinstance(expression, UnionExpression):
        return any(_contains_input(member) for member in expression.members)
    if isinstance(expression, AnnotatedExpression):
        return _contains_input(expression.value)
    return False


def _contains_typeforge_alias(
    value: object,
    aliases: tuple[TypeAliasType, ...],
) -> bool:
    origin = get_origin(value)
    alias = origin if isinstance(origin, TypeAliasType) else value
    if alias in _MARKERS or alias is Input:
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


def _marker_arity(
    expression: MarkerExpression,
    count: str,
) -> Failure[SchemaIssue]:
    return _issue(
        SchemaErrorCode.INVALID_MARKER,
        "evaluation",
        expression.marker.value,
        f"{expression.marker.value} requires {count} arguments",
    )


def _issue(
    code: SchemaErrorCode,
    phase: str,
    expression: str,
    message: str,
) -> Failure[SchemaIssue]:
    return Failure(SchemaIssue(code, phase, expression, message))


__all__ = [
    "Input",
    "Schema",
    "SchemaErrorCode",
    "SchemaIssue",
    "emit_core_schema",
    "evaluate_runtime_expression",
    "parse_runtime_expression",
]
