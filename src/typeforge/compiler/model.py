from dataclasses import dataclass
from enum import Enum
from pathlib import Path


@dataclass(frozen=True, slots=True, order=True)
class SourcePosition:
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class SourceSpan:
    path: Path
    start: SourcePosition
    end: SourcePosition


class MarkerKind(Enum):
    EACH = "Each"
    COLLECT = "Collect"
    IF = "If"
    ASSIGNABLE = "Assignable"
    EQUAL = "Equal"
    ALL = "All"
    ANY = "Any"
    NOT = "Not"
    MAP = "Map"
    CASE = "Case"
    DEFAULT = "Default"
    MAP_FIELDS = "MapFields"
    FIELD = "Field"
    OPTIONAL_FIELD = "OptionalField"
    READONLY_FIELD = "ReadonlyField"
    DROP = "Drop"
    KEY = "Key"
    VALUE = "Value"


@dataclass(frozen=True, slots=True)
class NameTypeExpression:
    source: str
    span: SourceSpan
    name: tuple[str, ...]
    qualified_name: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class AppliedTypeExpression:
    source: str
    span: SourceSpan
    constructor: TypeExpression
    arguments: tuple[TypeExpression, ...]


@dataclass(frozen=True, slots=True)
class UnionTypeExpression:
    source: str
    span: SourceSpan
    members: tuple[TypeExpression, ...]


@dataclass(frozen=True, slots=True)
class StarredTypeExpression:
    source: str
    span: SourceSpan
    item: TypeExpression


@dataclass(frozen=True, slots=True)
class MarkerTypeExpression:
    source: str
    span: SourceSpan
    marker: MarkerKind
    arguments: tuple[TypeExpression, ...]


@dataclass(frozen=True, slots=True)
class SchemaTypeExpression:
    source: str
    span: SourceSpan
    arguments: tuple[TypeExpression, ...]


@dataclass(frozen=True, slots=True)
class RuntimeInputTypeExpression:
    source: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class RawTypeExpression:
    source: str
    span: SourceSpan


type TypeExpression = (
    NameTypeExpression
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
    annotation: TypeExpression | None
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
    span: SourceSpan
    declaration: str


@dataclass(frozen=True, slots=True)
class FunctionDeclaration:
    name: str
    qualified_name: tuple[str, ...]
    parameters: tuple[Parameter, ...]
    returns: TypeExpression | None
    type_parameters: tuple[TypeParameter, ...]
    span: SourceSpan
    is_async: bool
    decorators: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TypeAliasDeclaration:
    name: str
    qualified_name: tuple[str, ...]
    type_parameters: tuple[TypeParameter, ...]
    value: TypeExpression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TypedDictField:
    name: str
    annotation: TypeExpression
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
    annotation: TypeExpression
    span: SourceSpan
    has_default: bool


@dataclass(frozen=True, slots=True)
class ClassDeclaration:
    name: str
    qualified_name: tuple[str, ...]
    type_parameters: tuple[TypeParameter, ...]
    bases: tuple[TypeExpression, ...]
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


def contains_marker(
    expression: TypeExpression, marker: MarkerKind | None = None
) -> bool:
    if isinstance(expression, MarkerTypeExpression):
        if marker is None or expression.marker is marker:
            return True
        return any(
            contains_marker(argument, marker) for argument in expression.arguments
        )
    if isinstance(expression, SchemaTypeExpression):
        return any(
            contains_marker(argument, marker) for argument in expression.arguments
        )
    if isinstance(expression, AppliedTypeExpression):
        return contains_marker(expression.constructor, marker) or any(
            contains_marker(argument, marker) for argument in expression.arguments
        )
    if isinstance(expression, UnionTypeExpression):
        return any(contains_marker(member, marker) for member in expression.members)
    if isinstance(expression, StarredTypeExpression):
        return contains_marker(expression.item, marker)
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
