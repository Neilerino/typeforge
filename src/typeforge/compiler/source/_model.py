from dataclasses import dataclass
from enum import Enum
from pathlib import Path


@dataclass(frozen=True, slots=True, order=True)
class SourcePosition:
    """One-based line and zero-based column.

    Parsed syntax facts use UTF-8 byte columns. Syntax errors retain Python's
    character offsets for compatibility with existing failure presentation.
    """

    line: int
    column: int


@dataclass(frozen=True, slots=True)
class SourceSpan:
    path: Path
    start: SourcePosition
    end: SourcePosition


@dataclass(frozen=True, slots=True)
class ReturnSite:
    statement: SourceSpan
    expression: SourceSpan | None


@dataclass(frozen=True, slots=True)
class IdentifierOccurrence:
    """A name use or parameter declaration; its span may include an annotation."""

    name: str
    span: SourceSpan


class MarkerKind(Enum):
    EACH = "Each"
    COLLECT = "Collect"
    ASSIGNABLE = "Assignable"
    EQUAL = "Equal"
    ALL = "All"
    ANY = "Any"
    NOT = "Not"
    MAP = "Map"
    CASE = "Case"
    DEFAULT = "Default"
    FIELD = "Field"
    OPTIONAL_FIELD = "OptionalField"
    READONLY_FIELD = "ReadonlyField"
    DROP = "Drop"


@dataclass(frozen=True, slots=True)
class NameTypeExpression:
    source: str
    span: SourceSpan
    name: tuple[str, ...]
    qualified_name: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class CaptureTypeExpression:
    """A capture use retains the declaring token's source identity."""

    source: str
    span: SourceSpan
    name: str
    declaration: SourceSpan


@dataclass(frozen=True, slots=True)
class FieldReferenceTypeExpression:
    source: str
    span: SourceSpan
    name: str
    declaration: SourceSpan
    attribute: str | None = None


@dataclass(frozen=True, slots=True)
class RecordTypeExpression:
    source: str
    span: SourceSpan
    record: SourceTypeExpression
    binding: FieldReferenceTypeExpression
    transform: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class AppliedTypeExpression:
    source: str
    span: SourceSpan
    constructor: SourceTypeExpression
    arguments: tuple[SourceTypeExpression, ...]


@dataclass(frozen=True, slots=True)
class UnionTypeExpression:
    source: str
    span: SourceSpan
    members: tuple[SourceTypeExpression, ...]


@dataclass(frozen=True, slots=True)
class StarredTypeExpression:
    source: str
    span: SourceSpan
    item: SourceTypeExpression


@dataclass(frozen=True, slots=True)
class MarkerTypeExpression:
    source: str
    span: SourceSpan
    marker: MarkerKind
    arguments: tuple[SourceTypeExpression, ...]


@dataclass(frozen=True, slots=True)
class SchemaTypeExpression:
    source: str
    span: SourceSpan
    arguments: tuple[SourceTypeExpression, ...]


@dataclass(frozen=True, slots=True)
class RuntimeInputTypeExpression:
    source: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class RawTypeExpression:
    source: str
    span: SourceSpan


type SourceTypeExpression = (
    NameTypeExpression
    | CaptureTypeExpression
    | FieldReferenceTypeExpression
    | RecordTypeExpression
    | AppliedTypeExpression
    | UnionTypeExpression
    | StarredTypeExpression
    | MarkerTypeExpression
    | SchemaTypeExpression
    | RuntimeInputTypeExpression
    | RawTypeExpression
)


class ParameterKind(Enum):
    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    kind: ParameterKind
    annotation: SourceTypeExpression | None
    span: SourceSpan
    has_default: bool


class TypeParameterKind(Enum):
    TYPE_VAR = "type_var"
    TYPE_VAR_TUPLE = "type_var_tuple"
    PARAM_SPEC = "param_spec"


@dataclass(frozen=True, slots=True)
class TypeParameter:
    name: str
    kind: TypeParameterKind
    declaration: str


@dataclass(frozen=True, slots=True)
class FunctionDeclaration:
    name: str
    qualified_name: tuple[str, ...]
    parameters: tuple[Parameter, ...]
    returns: SourceTypeExpression | None
    type_parameters: tuple[TypeParameter, ...]
    span: SourceSpan
    is_async: bool
    decorators: tuple[str, ...] = ()
    decorator_spans: tuple[SourceSpan, ...] = ()
    body_span: SourceSpan | None = None


@dataclass(frozen=True, slots=True)
class TypeAliasDeclaration:
    name: str
    qualified_name: tuple[str, ...]
    type_parameters: tuple[TypeParameter, ...]
    value: SourceTypeExpression
    span: SourceSpan
    is_type_function: bool = False


@dataclass(frozen=True, slots=True)
class TypedDictField:
    name: str
    annotation: SourceTypeExpression
    required: bool
    readonly: bool
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TypedDictDeclaration:
    name: str
    qualified_name: tuple[str, ...]
    fields: tuple[TypedDictField, ...]
    bases: tuple[tuple[str, ...], ...]
    total: bool
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ClassField:
    name: str
    annotation: SourceTypeExpression
    span: SourceSpan
    has_default: bool


@dataclass(frozen=True, slots=True)
class ClassDeclaration:
    name: str
    qualified_name: tuple[str, ...]
    type_parameters: tuple[TypeParameter, ...]
    bases: tuple[SourceTypeExpression, ...]
    keywords: tuple[str, ...]
    decorators: tuple[str, ...]
    fields: tuple[ClassField, ...]
    methods: tuple[FunctionDeclaration, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class SourceModule:
    path: Path
    functions: tuple[FunctionDeclaration, ...]
    aliases: tuple[TypeAliasDeclaration, ...] = ()
    typed_dicts: tuple[TypedDictDeclaration, ...] = ()
    classes: tuple[ClassDeclaration, ...] = ()
    text: str = ""
    docstring_span: SourceSpan | None = None
    future_import_spans: tuple[SourceSpan, ...] = ()
    return_sites: tuple[ReturnSite, ...] = ()
    identifiers: tuple[IdentifierOccurrence, ...] = ()
    variable_annotations: tuple[SourceTypeExpression, ...] = ()
    captures: tuple[tuple[str, CaptureTypeExpression], ...] = ()


def contains_marker(
    expression: SourceTypeExpression, marker: MarkerKind | None = None
) -> bool:

    match expression:
        case RecordTypeExpression(record=record, transform=transform):
            return (
                marker is None
                or contains_marker(record, marker)
                or contains_marker(transform, marker)
            )

        case MarkerTypeExpression():
            return (
                marker is None
                or expression.marker is marker
                or any(
                    contains_marker(argument, marker)
                    for argument in expression.arguments
                )
            )

        case SchemaTypeExpression():
            return any(
                contains_marker(argument, marker) for argument in expression.arguments
            )

        case AppliedTypeExpression():
            return contains_marker(expression.constructor, marker) or any(
                contains_marker(argument, marker) for argument in expression.arguments
            )

        case UnionTypeExpression():
            return any(contains_marker(member, marker) for member in expression.members)

        case StarredTypeExpression():
            return contains_marker(expression.item, marker)

        case (
            NameTypeExpression()
            | CaptureTypeExpression()
            | FieldReferenceTypeExpression()
            | RuntimeInputTypeExpression()
            | RawTypeExpression()
        ):
            return False


def is_enriched(function: FunctionDeclaration) -> bool:
    annotations = tuple(
        parameter.annotation
        for parameter in function.parameters
        if parameter.annotation is not None
    )
    if function.returns is not None:
        annotations += (function.returns,)

    return any(contains_marker(annotation) for annotation in annotations)


def enriched_functions(module: SourceModule) -> tuple[FunctionDeclaration, ...]:
    return tuple(function for function in module.functions if is_enriched(function))
