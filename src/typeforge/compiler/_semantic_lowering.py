"""Lower compiler source expressions into the shared semantic model."""

import ast
from dataclasses import dataclass
from functools import singledispatch

from typeforge.compiler._markers import (
    AllMarker,
    AnyMarker,
    AssignableMarker,
    CaseMarker,
    DefaultMarker,
    DropMarker,
    EqualMarker,
    FieldMarker,
    KeyMarker,
    MapFieldsMarker,
    MapMarker,
    MarkerNormalizationError,
    NormalizedMarker,
    NotMarker,
    OptionalFieldMarker,
    ReadonlyFieldMarker,
    ValueMarker,
    normalize_marker,
)
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
)
from typeforge.compiler.model import (
    TypeExpression as SourceTypeExpression,
)
from typeforge.compiler.records import NamedType, ParameterizedType, StaticType
from typeforge.semantics import (
    AllExpression,
    AnyExpression,
    AssignableExpression,
    CaptureValuePattern,
    CaseExpression,
    DropExpression,
    EqualExpression,
    ExactTypePattern,
    Expression,
    FieldExpression,
    FieldName,
    InputReference,
    KeyReference,
    MapExpression,
    MapFieldsExpression,
    NotExpression,
    OptionalFieldExpression,
    ParameterizedTypePattern,
    ParameterizedTypeTemplate,
    ReadonlyFieldExpression,
    TypePattern,
    TypeReference,
    TypeTemplate,
    ValueReference,
)

type SemanticEnvironment = tuple[tuple[str, StaticType], ...]


@dataclass(frozen=True, slots=True)
class SemanticLoweringError(Exception):
    message: str


@singledispatch
def lower_semantic_expression(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
) -> Expression[StaticType]:
    raise SemanticLoweringError(
        f"unsupported record expression {type(expression).__name__}"
    )


@lower_semantic_expression.register
def _(
    expression: NameTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
) -> Expression[StaticType]:
    bound = dict(environment).get(expression.source)
    return TypeReference(bound if bound is not None else NamedType(expression.source))


@lower_semantic_expression.register
def _(
    expression: RawTypeExpression | UnionTypeExpression | StarredTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
) -> Expression[StaticType]:
    return TypeReference(NamedType(expression.source))


@lower_semantic_expression.register
def _(
    expression: RuntimeInputTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
) -> Expression[StaticType]:
    return InputReference()


@lower_semantic_expression.register
def _(
    expression: AppliedTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
) -> Expression[StaticType]:
    field_name = field_name_literal(expression)
    if field_name is not None:
        return field_name
    return TypeReference(_lower_concrete_type(expression, environment))


@lower_semantic_expression.register
def _(
    expression: MarkerTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
) -> Expression[StaticType]:
    marker = _normalize_semantic_marker(expression)

    def lower(item: SourceTypeExpression) -> Expression[StaticType]:
        return lower_semantic_expression(item, environment)

    match marker:
        case KeyMarker():
            return KeyReference()
        case ValueMarker():
            return ValueReference()
        case DropMarker():
            return DropExpression()
        case FieldMarker(key=key, value=value):
            return FieldExpression(lower(key), lower(value))
        case OptionalFieldMarker(key=key, value=value):
            return OptionalFieldExpression(lower(key), lower(value))
        case ReadonlyFieldMarker(key=key, value=value):
            return ReadonlyFieldExpression(lower(key), lower(value))
        case MapFieldsMarker(record=record, transform=transform):
            return MapFieldsExpression(
                lower(record),
                lower(transform),
                output_name,
            )
        case MapMarker(subject=subject, entries=entries):
            cases = tuple(
                CaseExpression(
                    _lower_case_test(entry.test, environment),
                    _lower_case_output(entry.output, environment),
                )
                for entry in entries
                if isinstance(entry, CaseMarker)
            )
            default = next(
                (
                    lower(entry.output)
                    for entry in entries
                    if isinstance(entry, DefaultMarker)
                ),
                None,
            )
            return MapExpression(lower(subject), cases, default)
        case EqualMarker(left=left, right=right):
            return EqualExpression(lower(left), lower(right))
        case AssignableMarker(left=left, right=right):
            return AssignableExpression(lower(left), lower(right))
        case AllMarker(items=items):
            return AllExpression(tuple(lower(item) for item in items))
        case AnyMarker(items=items):
            return AnyExpression(tuple(lower(item) for item in items))
        case NotMarker(item=item):
            return NotExpression(lower(item))
        case _:
            raise SemanticLoweringError(
                "unsupported record expression "
                f"{type(marker).__name__.removesuffix('Marker')}"
            )


def _lower_concrete_type(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
) -> StaticType:
    match expression:
        case NameTypeExpression(source=source):
            bound = dict(environment).get(source)
            return bound if bound is not None else NamedType(source)
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return ParameterizedType(
                origin=_lower_concrete_type(constructor, environment),
                arguments=tuple(
                    _lower_concrete_type(argument, environment)
                    for argument in arguments
                ),
            )
        case _:
            return NamedType(expression.source)


def _lower_case_test(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
) -> Expression[StaticType] | TypePattern[StaticType]:
    match expression:
        case AppliedTypeExpression():
            field_name = field_name_literal(expression)
            if field_name is not None:
                return field_name
            return _lower_type_pattern(expression, environment)
        case MarkerTypeExpression():
            marker = _normalize_semantic_marker(expression)
            if isinstance(marker, ValueMarker):
                return CaptureValuePattern()
        case _:
            pass

    return lower_semantic_expression(expression, environment)


def _lower_type_pattern(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
) -> TypePattern[StaticType]:
    match expression:
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return ParameterizedTypePattern(
                origin=_lower_concrete_type(constructor, environment),
                arguments=tuple(
                    _lower_type_pattern(argument, environment) for argument in arguments
                ),
            )
        case MarkerTypeExpression():
            marker = _normalize_semantic_marker(expression)
            if isinstance(marker, ValueMarker):
                return CaptureValuePattern()
            raise SemanticLoweringError(
                "unsupported type pattern "
                f"{type(marker).__name__.removesuffix('Marker')}"
            )
        case _:
            return ExactTypePattern(_lower_concrete_type(expression, environment))


def _lower_case_output(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
) -> Expression[StaticType]:
    if isinstance(expression, AppliedTypeExpression):
        field_name = field_name_literal(expression)
        if field_name is not None:
            return field_name
        return _lower_type_template(expression, environment)
    return lower_semantic_expression(expression, environment)


def _lower_type_template(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
) -> TypeTemplate[StaticType]:
    match expression:
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return ParameterizedTypeTemplate(
                origin=_lower_concrete_type(constructor, environment),
                arguments=tuple(
                    _lower_type_template(argument, environment)
                    for argument in arguments
                ),
            )
        case MarkerTypeExpression():
            marker = _normalize_semantic_marker(expression)
            if isinstance(marker, ValueMarker):
                return ValueReference()
            raise SemanticLoweringError(
                "unsupported type template "
                f"{type(marker).__name__.removesuffix('Marker')}"
            )
        case _:
            return TypeReference(_lower_concrete_type(expression, environment))


def _normalize_semantic_marker(
    expression: MarkerTypeExpression,
) -> NormalizedMarker:
    try:
        return normalize_marker(expression)
    except MarkerNormalizationError as error:
        raise SemanticLoweringError(error.message) from error


def field_name_literal(expression: AppliedTypeExpression) -> FieldName | None:
    """Lower a one-string Literal application into a semantic field name."""
    if not isinstance(expression.constructor, NameTypeExpression):
        return None
    if expression.constructor.source != "Literal" or len(expression.arguments) != 1:
        return None
    argument = expression.arguments[0]
    if not isinstance(argument, RawTypeExpression):
        return None
    try:
        value = ast.literal_eval(argument.source)
    except SyntaxError, ValueError:
        return None
    return FieldName(value) if isinstance(value, str) else None
