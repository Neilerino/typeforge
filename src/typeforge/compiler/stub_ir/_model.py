"""Immutable target-side representation used by compiler stages."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeIs

from typeforge.compiler.source import SourceSpan


@dataclass(frozen=True, slots=True)
class TypeName:
    name: str


@dataclass(frozen=True, slots=True)
class TypeVariable:
    name: str


@dataclass(frozen=True, slots=True)
class TypeApplication:
    constructor: StubTypeExpression
    arguments: tuple[StubTypeExpression, ...]


@dataclass(frozen=True, slots=True)
class FixedTuple:
    items: tuple[StubTypeExpression, ...]


@dataclass(frozen=True, slots=True)
class HomogeneousTuple:
    item: StubTypeExpression


@dataclass(frozen=True, slots=True)
class EachType:
    item: StubTypeExpression


@dataclass(frozen=True, slots=True)
class CollectType:
    item: StubTypeExpression


@dataclass(frozen=True, slots=True)
class UnpackedType:
    item: StubTypeExpression


@dataclass(frozen=True, slots=True)
class LiteralType:
    value: str | bytes | int | bool | None


@dataclass(frozen=True, slots=True)
class UnionExpression:
    members: tuple[StubTypeExpression, ...]


@dataclass(frozen=True, slots=True)
class EqualPredicate:
    left: StubTypeExpression
    right: StubTypeExpression


@dataclass(frozen=True, slots=True)
class AssignablePredicate:
    source: StubTypeExpression
    target: StubTypeExpression


@dataclass(frozen=True, slots=True)
class AllPredicate:
    predicates: tuple[Predicate, ...]


@dataclass(frozen=True, slots=True)
class AnyPredicate:
    predicates: tuple[Predicate, ...]


@dataclass(frozen=True, slots=True)
class NotPredicate:
    predicate: Predicate


type Predicate = (
    EqualPredicate | AssignablePredicate | AllPredicate | AnyPredicate | NotPredicate
)


def is_predicate(value: object) -> TypeIs[Predicate]:
    return isinstance(
        value,
        EqualPredicate
        | AssignablePredicate
        | AllPredicate
        | AnyPredicate
        | NotPredicate,
    )


@dataclass(frozen=True, slots=True)
class MapCase:
    test: StubTypeExpression | Predicate
    output_type: StubTypeExpression


@dataclass(frozen=True, slots=True)
class MapType:
    subject: StubTypeExpression
    cases: tuple[MapCase, ...]
    default: StubTypeExpression


@dataclass(frozen=True, slots=True)
class MapValueType:
    pass


@dataclass(frozen=True, slots=True)
class FieldType:
    name: StubTypeExpression
    value: StubTypeExpression
    required: bool = True
    readonly: bool = False


@dataclass(frozen=True, slots=True)
class MapFieldsType:
    record: StubTypeExpression
    transform: StubTypeExpression


@dataclass(frozen=True, slots=True)
class SchemaType:
    item: StubTypeExpression


@dataclass(frozen=True, slots=True)
class RuntimeInputType:
    pass


type StubTypeExpression = (
    TypeName
    | TypeVariable
    | TypeApplication
    | FixedTuple
    | HomogeneousTuple
    | EachType
    | CollectType
    | UnpackedType
    | LiteralType
    | UnionExpression
    | MapType
    | MapValueType
    | FieldType
    | MapFieldsType
    | SchemaType
    | RuntimeInputType
)


class ParameterKind(StrEnum):
    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    annotation: StubTypeExpression
    kind: ParameterKind = ParameterKind.POSITIONAL_OR_KEYWORD
    default: str | None = None


@dataclass(frozen=True, slots=True)
class FunctionDeclaration:
    name: str
    parameters: tuple[Parameter, ...]
    return_type: StubTypeExpression
    type_parameters: tuple[str, ...] = ()
    is_async: bool = False
    decorators: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OverloadDeclaration:
    signatures: tuple[FunctionDeclaration, ...]
    fallback: FunctionDeclaration
    decorator: str = "overload"


@dataclass(frozen=True, slots=True)
class TypeAliasDeclaration:
    name: str
    value: StubTypeExpression
    type_parameters: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VariableDeclaration:
    name: str
    annotation: StubTypeExpression


@dataclass(frozen=True, slots=True)
class ClassField:
    name: str
    annotation: StubTypeExpression
    default: str | None = None


@dataclass(frozen=True, slots=True)
class ClassDeclaration:
    name: str
    bases: tuple[StubTypeExpression, ...]
    fields: tuple[ClassField, ...]
    methods: tuple[FunctionDeclaration | OverloadDeclaration, ...]
    type_parameters: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    decorators: tuple[str, ...] = ()


type Declaration = (
    FunctionDeclaration
    | OverloadDeclaration
    | TypeAliasDeclaration
    | VariableDeclaration
    | ClassDeclaration
)

type GeneratedElement = Declaration | StubTypeExpression


@dataclass(frozen=True, slots=True)
class GeneratedElementOrigin[OriginType]:
    origin: OriginType
    generated: GeneratedElement


@dataclass(frozen=True, slots=True, order=True)
class Import:
    module: str
    alias: str | None = None


@dataclass(frozen=True, slots=True, order=True)
class ImportFrom:
    module: str
    names: tuple[str, ...]


type ModuleImport = Import | ImportFrom


@dataclass(frozen=True, slots=True)
class StubModule:
    name: str
    declarations: tuple[Declaration, ...]
    imports: tuple[ModuleImport, ...] = ()
    origins: tuple[GeneratedElementOrigin[SourceSpan], ...] = ()
    expressions: tuple[StubTypeExpression, ...] = ()
