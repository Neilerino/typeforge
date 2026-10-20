"""Lower compiler source expressions into the shared semantic model."""

import ast
from dataclasses import dataclass
from functools import singledispatch
from typing import Literal

from typeforge.compiler.semantic_adapter._types import (
    NEVER,
    NamedType,
    ParameterizedType,
    StaticType,
    is_static,
    union_of,
)
from typeforge.compiler.source import (
    AllMarker,
    AnyMarker,
    AppliedTypeExpression,
    AssignableMarker,
    CaptureTypeExpression,
    CaseMarker,
    DefaultMarker,
    DropMarker,
    EqualMarker,
    FieldMarker,
    KeyMarker,
    MapFieldsMarker,
    MapMarker,
    MarkerNormalizationError,
    MarkerTypeExpression,
    NameTypeExpression,
    NormalizedMarker,
    NotMarker,
    OptionalFieldMarker,
    RawTypeExpression,
    ReadonlyFieldMarker,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
    ValueMarker,
    normalize_marker,
)
from typeforge.semantics import (
    AllExpression,
    AlternativeTypePattern,
    AnyExpression,
    AssignableExpression,
    CaptureReference,
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
    TypeSymbol,
    TypeValue,
    TypeValueReference,
    UnionExpression,
    ValueReference,
)

type SemanticRole = Literal["type", "output", "field-name"]


type SemanticEnvironment = tuple[tuple[str, StaticType | TypeValue[StaticType]], ...]


@dataclass(frozen=True, slots=True)
class SemanticLoweringError(Exception):
    message: str


@singledispatch
def lower_semantic_expression(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> Expression[StaticType]:
    raise SemanticLoweringError(
        f"unsupported record expression {type(expression).__name__}"
    )


@lower_semantic_expression.register
def _(
    expression: NameTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> Expression[StaticType]:
    bound = dict(environment).get(expression.source)
    if bound is not None and not is_static(bound):
        return TypeValueReference(bound)

    return TypeReference(_lower_concrete_type(expression, environment))


@lower_semantic_expression.register
def _(
    expression: CaptureTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> CaptureReference:
    return lower_capture_reference(expression)


def lower_capture_reference(expression: CaptureTypeExpression) -> CaptureReference:
    declaration = expression.declaration
    return CaptureReference(
        TypeSymbol(
            (
                str(declaration.path),
                str(declaration.start.line),
                str(declaration.start.column),
            ),
            expression.name,
        )
    )


@lower_semantic_expression.register
def _(
    expression: SchemaTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> Expression[StaticType]:
    if len(expression.arguments) != 1:
        raise SemanticLoweringError("Schema requires one type argument")

    return lower_semantic_expression(
        expression.arguments[0], environment, output_name, role=role
    )


@lower_semantic_expression.register
def _(
    expression: RawTypeExpression | StarredTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> Expression[StaticType]:
    return TypeReference(NamedType(expression.source))


@lower_semantic_expression.register
def _(
    expression: UnionTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> Expression[StaticType]:
    return UnionExpression(
        tuple(
            lower_semantic_expression(member, environment, role=role)
            for member in expression.members
        )
    )


@lower_semantic_expression.register
def _(
    expression: RuntimeInputTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> Expression[StaticType]:
    return InputReference()


@lower_semantic_expression.register
def _(
    expression: AppliedTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> Expression[StaticType]:
    if (
        role == "field-name"
        and (field_name := field_name_literal(expression)) is not None
    ):
        return field_name

    if role == "output" or _requires_evaluation(expression, environment):
        return _lower_type_template(expression, environment)

    return TypeReference(_lower_concrete_type(expression, environment))


@lower_semantic_expression.register
def _(
    expression: MarkerTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> Expression[StaticType]:
    marker = _normalize_semantic_marker(expression)

    def lower(
        item: SourceTypeExpression, item_role: SemanticRole = "type"
    ) -> Expression[StaticType]:
        return lower_semantic_expression(item, environment, role=item_role)

    match marker:
        case KeyMarker():
            return KeyReference()
        case ValueMarker():
            return ValueReference()
        case DropMarker():
            return DropExpression()
        case FieldMarker(key=key, value=value):
            return FieldExpression(lower(key, "field-name"), lower(value, "output"))
        case OptionalFieldMarker(key=key, value=value):
            return OptionalFieldExpression(
                lower(key, "field-name"), lower(value, "output")
            )
        case ReadonlyFieldMarker(key=key, value=value):
            return ReadonlyFieldExpression(
                lower(key, "field-name"), lower(value, "output")
            )
        case MapFieldsMarker(record=record, transform=transform):
            return MapFieldsExpression(
                lower(record),
                lower(transform),
                output_name,
            )
        case MapMarker(subject=subject, entries=entries):
            subject_role: SemanticRole = (
                "field-name" if _is_key_expression(subject) else "type"
            )
            output_role: SemanticRole = (
                "field-name" if role == "field-name" else "output"
            )
            cases = tuple(
                CaseExpression(
                    _lower_case_test(entry.test, environment, role=subject_role),
                    lower(entry.output, output_role),
                )
                for entry in entries
                if isinstance(entry, CaseMarker)
            )
            default = next(
                (
                    lower(entry.output, output_role)
                    for entry in entries
                    if isinstance(entry, DefaultMarker)
                ),
                None,
            )
            return MapExpression(lower(subject, subject_role), cases, default)
        case EqualMarker(left=left, right=right):
            operand_role: SemanticRole = (
                "field-name"
                if _is_key_expression(left) or _is_key_expression(right)
                else "type"
            )
            return EqualExpression(
                lower(left, operand_role), lower(right, operand_role)
            )
        case AssignableMarker(left=left, right=right):
            return AssignableExpression(lower(left), lower(right))
        case AllMarker(items=items):
            return AllExpression(tuple(lower(item, role) for item in items))
        case AnyMarker(items=items):
            return AnyExpression(tuple(lower(item, role) for item in items))
        case NotMarker(item=item):
            return NotExpression(lower(item, role))
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
            if bound is not None and not is_static(bound):
                raise SemanticLoweringError(
                    f"{source} requires semantic type evaluation"
                )

            if bound is None and source in {
                "Never",
                "typing.Never",
                "typing_extensions.Never",
            }:
                return NEVER

            if bound is not None:
                return bound

            qualified = expression.qualified_name
            identity = (
                ".".join(qualified)
                if qualified is not None
                and qualified[:-1] in {("typing",), ("collections", "abc")}
                and qualified[-1]
                in {
                    "Sequence",
                    "Mapping",
                    "List",
                    "Set",
                    "Dict",
                    "FrozenSet",
                    "Tuple",
                    "Any",
                }
                else None
            )
            return NamedType(source, identity=identity)
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return ParameterizedType(
                origin=_lower_concrete_type(constructor, environment),
                arguments=tuple(
                    _lower_concrete_type(argument, environment)
                    for argument in arguments
                ),
            )
        case UnionTypeExpression(members=members):
            return union_of(
                *(_lower_concrete_type(member, environment) for member in members)
            )
        case _:
            return NamedType(expression.source)


def _lower_case_test(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
    *,
    role: SemanticRole,
) -> Expression[StaticType] | TypePattern[StaticType]:
    match expression:
        case UnionTypeExpression() if _requires_evaluation(expression, environment):
            return _lower_type_pattern(expression, environment)
        case AppliedTypeExpression():
            field_name = field_name_literal(expression)
            if role == "field-name" and field_name is not None:
                return field_name

            return _lower_type_pattern(expression, environment)
        case MarkerTypeExpression():
            marker = _normalize_semantic_marker(expression)
            if isinstance(marker, ValueMarker):
                raise SemanticLoweringError(
                    "Value is a field reference; "
                    "declare Capture for structural matching"
                )

        case _:
            pass

    return lower_semantic_expression(expression, environment, role=role)


def _lower_type_pattern(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
) -> TypePattern[StaticType]:
    match expression:
        case UnionTypeExpression(members=members) if _requires_evaluation(
            expression, environment
        ):
            return AlternativeTypePattern(
                tuple(_lower_type_pattern(member, environment) for member in members)
            )
        case CaptureTypeExpression():
            return lower_capture_reference(expression)
        case NameTypeExpression(source=source) if (
            bound := dict(environment).get(source)
        ) is not None and not is_static(bound):
            return TypeValueReference(bound)
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
                raise SemanticLoweringError(
                    "Value is a field reference; "
                    "declare Capture for structural matching"
                )

            raise SemanticLoweringError(
                "unsupported type pattern "
                f"{type(marker).__name__.removesuffix('Marker')}"
            )
        case _:
            return ExactTypePattern(_lower_concrete_type(expression, environment))


def _lower_type_template(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
) -> Expression[StaticType]:
    match expression:
        case UnionTypeExpression(members=members):
            return UnionExpression(
                tuple(_lower_type_template(member, environment) for member in members)
            )
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return ParameterizedTypeTemplate(
                origin=_lower_concrete_type(constructor, environment),
                arguments=tuple(
                    _lower_type_template(argument, environment)
                    for argument in arguments
                ),
            )
        case _:
            return lower_semantic_expression(expression, environment, role="output")


def _normalize_semantic_marker(
    expression: MarkerTypeExpression,
) -> NormalizedMarker:
    try:
        return normalize_marker(expression)
    except MarkerNormalizationError as error:
        raise SemanticLoweringError(error.message) from error


def _requires_evaluation(
    expression: SourceTypeExpression, environment: SemanticEnvironment
) -> bool:
    match expression:
        case (
            MarkerTypeExpression()
            | CaptureTypeExpression()
            | SchemaTypeExpression()
            | RuntimeInputTypeExpression()
        ):
            return True
        case NameTypeExpression(source=source):
            bound = dict(environment).get(source)
            return bound is not None and not is_static(bound)
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return any(
                _requires_evaluation(item, environment)
                for item in (constructor, *arguments)
            )
        case UnionTypeExpression(members=members):
            return any(_requires_evaluation(item, environment) for item in members)
        case _:
            return False


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


def _is_key_expression(expression: SourceTypeExpression) -> bool:
    if not isinstance(expression, MarkerTypeExpression):
        return False

    match _normalize_semantic_marker(expression):
        case KeyMarker():
            return True
        case MapMarker(subject=subject):
            return _is_key_expression(subject)
        case _:
            return False
