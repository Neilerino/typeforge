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
    FieldConstructionTypeExpression,
    FieldReferenceTypeExpression,
    FieldReplacementTypeExpression,
    MapMarker,
    MarkerNormalizationError,
    MarkerTypeExpression,
    NameTypeExpression,
    NormalizedMarker,
    NotMarker,
    RawTypeExpression,
    RecordTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
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
    FieldNameReference,
    FieldReference,
    FieldReplacementExpression,
    FieldTypeReference,
    InputReference,
    MapExpression,
    NotExpression,
    ParameterizedTypePattern,
    ParameterizedTypeTemplate,
    RecordExpression,
    TypePattern,
    TypeReference,
    TypeSymbol,
    TypeValue,
    TypeValueReference,
    UnionExpression,
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
    expression: FieldReplacementTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> FieldReplacementExpression[StaticType]:
    return FieldReplacementExpression(
        lower_semantic_expression(expression.field, environment, role="output"),
        name=None
        if expression.name is None
        else lower_semantic_expression(expression.name, environment, role="field-name"),
        value=None
        if expression.value is None
        else lower_semantic_expression(expression.value, environment, role="output"),
        required=expression.required,
        readonly=expression.readonly,
    )


def _field_symbol(expression: FieldReferenceTypeExpression) -> TypeSymbol:
    declaration = expression.declaration
    return TypeSymbol(
        (
            str(declaration.path),
            str(declaration.start.line),
            str(declaration.start.column),
        ),
        expression.name,
    )


@lower_semantic_expression.register
def _(
    expression: FieldConstructionTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> FieldExpression[StaticType]:
    return FieldExpression(
        lower_semantic_expression(expression.name, environment, role="field-name"),
        lower_semantic_expression(expression.value, environment, role="output"),
        required=expression.required,
        readonly=expression.readonly,
    )


@lower_semantic_expression.register
def _(
    expression: FieldReferenceTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> FieldReference | FieldNameReference | FieldTypeReference:
    symbol = _field_symbol(expression)
    match expression.attribute:
        case "name":
            return FieldNameReference(symbol)
        case "type":
            return FieldTypeReference(symbol)
        case _:
            return FieldReference(symbol)


@lower_semantic_expression.register
def _(
    expression: RecordTypeExpression,
    environment: SemanticEnvironment,
    output_name: str | None = None,
    *,
    role: SemanticRole = "type",
) -> RecordExpression[StaticType]:
    return RecordExpression(
        lower_semantic_expression(expression.record, environment),
        _field_symbol(expression.binding),
        lower_semantic_expression(expression.transform, environment, role="output"),
        output_name,
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
    if role == "field-name" and isinstance(expression, RawTypeExpression):
        try:
            name = ast.literal_eval(expression.source)
        except SyntaxError, ValueError:
            pass
        else:
            if isinstance(name, str):
                return FieldName(name)

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
        case DropMarker():
            return DropExpression()
        case MapMarker(subject=subject, entries=entries):
            subject_role: SemanticRole = (
                "field-name" if _is_field_name_expression(subject) else "type"
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
                if _is_field_name_expression(left) or _is_field_name_expression(right)
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
            | FieldReferenceTypeExpression()
            | FieldConstructionTypeExpression()
            | FieldReplacementTypeExpression()
            | RecordTypeExpression()
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


def _is_field_name_expression(expression: SourceTypeExpression) -> bool:
    if isinstance(expression, FieldReferenceTypeExpression):
        return expression.attribute == "name"

    if not isinstance(expression, MarkerTypeExpression):
        return False

    match _normalize_semantic_marker(expression):
        case MapMarker(subject=subject):
            return _is_field_name_expression(subject)
        case _:
            return False
