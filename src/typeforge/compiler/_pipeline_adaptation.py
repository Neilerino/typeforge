"""Adapt source syntax into lowering IR and expand semantic type relationships."""

from functools import singledispatch

from returns.result import Failure, Result, safe

from typeforge.compiler._markers import (
    AllMarker,
    AnyMarker,
    AssignableMarker,
    CaseMarker,
    CollectMarker,
    DefaultMarker,
    DropMarker,
    EachMarker,
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
from typeforge.compiler._pipeline_models import (
    AdaptationError,
    SemanticRelationshipAlias,
)
from typeforge.compiler._pipeline_utils import (
    annotation_contains_default_never,
    collect_imports,
    merge_imports,
)
from typeforge.compiler._semantic_evaluation import evaluate_source_semantics
from typeforge.compiler._semantic_lowering import UnresolvedTypeBinding
from typeforge.compiler._source_type_tree import rewrite_source_type_children
from typeforge.compiler._static_type_adaptation import static_type_expression
from typeforge.compiler._type_tree import rewrite_type, rewrite_type_children
from typeforge.compiler.lowering import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    ClassDeclaration,
    ClassField,
    CollectType,
    Declaration,
    EachType,
    EqualPredicate,
    FunctionDeclaration,
    HomogeneousTuple,
    ImportFrom,
    MapCase,
    MapType,
    MapValueType,
    ModuleImport,
    NotPredicate,
    Parameter,
    ParameterKind,
    Predicate,
    RuntimeInputType,
    SchemaType,
    StubModule,
    TypeAliasDeclaration,
    TypeApplication,
    TypeExpression,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
)
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceModule,
    StarredTypeExpression,
    UnionTypeExpression,
)
from typeforge.compiler.model import (
    ClassDeclaration as SourceClass,
)
from typeforge.compiler.model import (
    FunctionDeclaration as SourceFunction,
)
from typeforge.compiler.model import (
    ParameterKind as SourceParameterKind,
)
from typeforge.compiler.model import (
    TypeAliasDeclaration as SourceTypeAlias,
)
from typeforge.compiler.model import (
    TypeExpression as SourceTypeExpression,
)
from typeforge.compiler.records import NamedType
from typeforge.semantics import DeferredMap, ResolvedType


def substitute_type(
    expression: TypeExpression, variable: str, replacement: TypeExpression
) -> TypeExpression:
    target = TypeVariable(variable)
    return rewrite_type(
        expression,
        lambda current: replacement if current == target else None,
    )


@safe(exceptions=(AdaptationError,))
def adapt_source_module(
    module: SourceModule,
) -> StubModule:
    imports: tuple[ModuleImport, ...] = collect_imports(module.path)
    semantic_aliases = _collect_semantic_relationship_aliases(module.aliases)
    declarations: list[tuple[int, Declaration]] = []
    for alias in module.aliases:
        if len(alias.qualified_name) != 1:
            continue
        parameter_names = tuple(parameter.name for parameter in alias.type_parameters)
        lowered_alias = TypeAliasDeclaration(
            alias.name,
            _adapt_alias_fallback(
                alias.name,
                alias.value,
                parameter_names,
                semantic_aliases,
            ),
            tuple(parameter.declaration for parameter in alias.type_parameters),
        )
        declarations.append(
            (
                alias.span.start.line,
                TypeAliasDeclaration(
                    lowered_alias.name,
                    expand_map_aliases(lowered_alias.value, semantic_aliases),
                    lowered_alias.type_parameters,
                ),
            )
        )
    for source_class in module.classes:
        declarations.append(
            (
                source_class.span.start.line,
                expand_class_map_aliases(
                    _adapt_class(source_class, semantic_aliases),
                    semantic_aliases,
                ),
            )
        )
    for function in module.functions:
        if len(function.qualified_name) != 1:
            continue
        declarations.append(
            (
                function.span.start.line,
                expand_function_map_aliases(
                    _adapt_function(function, aliases=semantic_aliases),
                    semantic_aliases,
                ),
            )
        )
    all_functions = (
        *module.functions,
        *(method for source_class in module.classes for method in source_class.methods),
    )
    if any(
        function.returns is None
        or any(parameter.annotation is None for parameter in function.parameters)
        for function in all_functions
    ):
        imports = merge_imports((*imports, ImportFrom("typing", ("Any",))))
    if any(
        annotation_contains_default_never(function.returns)
        or any(
            annotation_contains_default_never(parameter.annotation)
            for parameter in function.parameters
        )
        for function in module.functions
    ):
        imports = merge_imports((*imports, ImportFrom("typing", ("Never",))))
    ordered = tuple(
        declaration for _, declaration in sorted(declarations, key=lambda item: item[0])
    )
    return StubModule(module.path.stem, ordered, imports)


@safe(exceptions=(AdaptationError,))
def collect_semantic_relationship_aliases(
    aliases: tuple[SourceTypeAlias, ...],
) -> tuple[SemanticRelationshipAlias, ...]:
    return _collect_semantic_relationship_aliases(aliases)


def _collect_semantic_relationship_aliases(
    aliases: tuple[SourceTypeAlias, ...],
) -> tuple[SemanticRelationshipAlias, ...]:
    semantic: list[SemanticRelationshipAlias] = []
    for alias in aliases:
        value = schema_inner_expression(alias.value)
        if not isinstance(value, MarkerTypeExpression):
            continue
        try:
            normalized = normalize_marker(value)
        except MarkerNormalizationError:
            continue
        if not isinstance(normalized, MapMarker):
            continue
        if len(alias.type_parameters) != 1:
            raise AdaptationError(
                alias.name,
                alias.value.source,
                "relationship aliases require exactly one type parameter",
            )
        parameter = alias.type_parameters[0].name
        relationship = _adapt_type_expression(value, alias.name, (parameter,))
        if not isinstance(relationship, MapType):
            raise AssertionError("relationship adaptation produced a plain type")
        semantic.append(
            SemanticRelationshipAlias(
                name=alias.name,
                parameter=parameter,
                semantic_source=value,
                callable_relationship=relationship,
            )
        )
    return tuple(semantic)


def schema_inner_expression(expression: SourceTypeExpression) -> SourceTypeExpression:
    if isinstance(expression, SchemaTypeExpression) and len(expression.arguments) == 1:
        return expression.arguments[0]
    return expression


def _adapt_schema_type(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> TypeExpression:
    expanded = _expand_semantic_aliases(expression, aliases)
    if isinstance(expanded, MarkerTypeExpression) and isinstance(
        _normalize_marker(declaration, expanded), MapMarker
    ):
        return _evaluate_schema_map(
            expanded,
            declaration,
            type_parameters,
        )

    match expanded:
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return TypeApplication(
                _adapt_schema_type(
                    constructor,
                    declaration,
                    type_parameters,
                    aliases,
                ),
                tuple(
                    _adapt_schema_type(
                        argument,
                        declaration,
                        type_parameters,
                        aliases,
                    )
                    for argument in arguments
                ),
            )
        case UnionTypeExpression(members=members):
            return UnionExpression(
                tuple(
                    _adapt_schema_type(
                        member,
                        declaration,
                        type_parameters,
                        aliases,
                    )
                    for member in members
                )
            )
        case StarredTypeExpression(item=item):
            return UnpackedType(
                _adapt_schema_type(item, declaration, type_parameters, aliases)
            )
        case SchemaTypeExpression(arguments=(item,)):
            return _adapt_schema_type(item, declaration, type_parameters, aliases)
        case _:
            return _adapt_type_expression(
                expanded,
                declaration,
                type_parameters,
                aliases,
            )


def _evaluate_schema_map(
    expression: MarkerTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    environment = tuple(
        (name, UnresolvedTypeBinding(NamedType(name))) for name in type_parameters
    )
    evaluated_result = evaluate_source_semantics(expression, environment)
    if isinstance(evaluated_result, Failure):
        raise AdaptationError(
            declaration,
            expression.source,
            evaluated_result.failure().message,
        )

    match evaluated_result.unwrap():
        case ResolvedType(value):
            return static_type_expression(value)
        case DeferredMap(possible_output=ResolvedType(value)):
            return static_type_expression(value)
        case value:
            raise AdaptationError(
                declaration,
                expression.source,
                "Schema Map must resolve to a type",
            )


def _expand_semantic_aliases(
    expression: SourceTypeExpression,
    aliases: tuple[SemanticRelationshipAlias, ...],
    active: tuple[str, ...] = (),
) -> SourceTypeExpression:
    if isinstance(expression, AppliedTypeExpression) and isinstance(
        expression.constructor, NameTypeExpression
    ):
        alias = next(
            (
                item
                for item in aliases
                if item.name == expression.constructor.source
                and len(expression.arguments) == 1
            ),
            None,
        )
        if alias is not None:
            if alias.name in active:
                cycle = " -> ".join((*active, alias.name))
                raise AdaptationError(
                    alias.name,
                    expression.source,
                    f"cyclic relationship alias: {cycle}",
                )
            argument = _expand_semantic_aliases(
                expression.arguments[0], aliases, active
            )
            substituted = _substitute_source_type(
                alias.semantic_source,
                alias.parameter,
                argument,
            )
            return _expand_semantic_aliases(
                substituted,
                aliases,
                (*active, alias.name),
            )

    return rewrite_source_type_children(
        expression,
        lambda child: _expand_semantic_aliases(child, aliases, active),
    )


def _substitute_source_type(
    expression: SourceTypeExpression,
    variable: str,
    replacement: SourceTypeExpression,
) -> SourceTypeExpression:
    if isinstance(expression, NameTypeExpression) and expression.source == variable:
        return replacement
    return rewrite_source_type_children(
        expression,
        lambda child: _substitute_source_type(child, variable, replacement),
    )


def collect_semantic_map_aliases(
    aliases: tuple[SourceTypeAlias, ...],
) -> Result[tuple[SemanticRelationshipAlias, ...], AdaptationError]:
    return collect_semantic_relationship_aliases(aliases)


def expand_class_map_aliases(
    declaration: ClassDeclaration,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> ClassDeclaration:
    return ClassDeclaration(
        name=declaration.name,
        bases=tuple(expand_map_aliases(base, aliases) for base in declaration.bases),
        fields=tuple(
            ClassField(
                field.name,
                expand_map_aliases(field.annotation, aliases),
                field.default,
            )
            for field in declaration.fields
        ),
        methods=tuple(
            expand_function_map_aliases(method, aliases)
            if isinstance(method, FunctionDeclaration)
            else method
            for method in declaration.methods
        ),
        type_parameters=declaration.type_parameters,
        keywords=declaration.keywords,
        decorators=declaration.decorators,
    )


def expand_function_map_aliases(
    declaration: FunctionDeclaration,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> FunctionDeclaration:
    return FunctionDeclaration(
        name=declaration.name,
        parameters=tuple(
            Parameter(
                parameter.name,
                expand_map_aliases(parameter.annotation, aliases),
                parameter.kind,
                parameter.default,
            )
            for parameter in declaration.parameters
        ),
        return_type=expand_map_aliases(declaration.return_type, aliases),
        type_parameters=declaration.type_parameters,
        is_async=declaration.is_async,
        decorators=declaration.decorators,
    )


def expand_map_aliases(
    expression: TypeExpression,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> TypeExpression:
    match expression:
        case SchemaType(item):
            return expand_map_aliases(item, aliases)
        case TypeApplication(TypeName(name), (argument,)):
            alias = next((item for item in aliases if item.name == name), None)
            if alias is not None:
                return substitute_type(
                    alias.callable_relationship,
                    alias.parameter,
                    expand_map_aliases(argument, aliases),
                )
        case _:
            pass
    return rewrite_type_children(
        expression,
        lambda child: expand_map_aliases(child, aliases),
    )


@safe(exceptions=(AdaptationError,))
def adapt_alias(
    alias: SourceTypeAlias,
    *,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> TypeAliasDeclaration:
    parameter_names = tuple(parameter.name for parameter in alias.type_parameters)
    type_parameters = tuple(
        parameter.declaration for parameter in alias.type_parameters
    )
    return TypeAliasDeclaration(
        alias.name,
        _adapt_alias_fallback(alias.name, alias.value, parameter_names, aliases),
        type_parameters,
    )


@safe(exceptions=(AdaptationError,))
def adapt_class(
    source_class: SourceClass,
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> ClassDeclaration:
    return _adapt_class(source_class, aliases)


def _adapt_class(
    source_class: SourceClass,
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> ClassDeclaration:
    parameter_names = tuple(
        parameter.name for parameter in source_class.type_parameters
    )
    bases = _adapt_type_expressions(
        source_class.bases,
        source_class.name,
        parameter_names,
        aliases,
    )
    fields = tuple(
        ClassField(
            field.name,
            _adapt_type_expression(
                field.annotation,
                source_class.name,
                parameter_names,
                aliases,
            ),
            "..." if field.has_default else None,
        )
        for field in source_class.fields
    )
    methods = tuple(
        _adapt_function(method, parameter_names, aliases)
        for method in source_class.methods
    )
    return ClassDeclaration(
        name=source_class.name,
        bases=bases,
        fields=fields,
        methods=methods,
        type_parameters=tuple(
            parameter.declaration for parameter in source_class.type_parameters
        ),
        keywords=source_class.keywords,
        decorators=source_class.decorators,
    )


def _adapt_alias_fallback(
    declaration: str,
    expression: SourceTypeExpression,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression:
    if not isinstance(expression, MarkerTypeExpression):
        return _adapt_type_expression(
            expression,
            declaration,
            type_parameters,
            aliases,
        )
    marker = _normalize_marker(declaration, expression)
    match marker:
        case EachMarker(item=item):
            return _adapt_alias_fallback(declaration, item, type_parameters, aliases)
        case CollectMarker(item=item):
            return HomogeneousTuple(
                _adapt_alias_fallback(declaration, item, type_parameters, aliases)
            )
        case MapMarker() | MapFieldsMarker():
            return TypeName("object")
        case (
            AssignableMarker() | EqualMarker() | AllMarker() | AnyMarker() | NotMarker()
        ):
            return TypeName("bool")
        case (
            CaseMarker(output=value)
            | DefaultMarker(output=value)
            | FieldMarker(value=value)
            | OptionalFieldMarker(value=value)
            | ReadonlyFieldMarker(value=value)
        ):
            return _adapt_alias_fallback(declaration, value, type_parameters, aliases)
        case DropMarker():
            return TypeName("Never")
        case KeyMarker():
            return TypeName("str")
        case ValueMarker():
            return TypeName("object")


@safe(exceptions=(AdaptationError,))
def adapt_function(
    function: SourceFunction,
    enclosing_type_parameters: tuple[str, ...] = (),
    *,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> FunctionDeclaration:
    return _adapt_function(function, enclosing_type_parameters, aliases)


def _adapt_function(
    function: SourceFunction,
    enclosing_type_parameters: tuple[str, ...] = (),
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> FunctionDeclaration:
    parameter_names = tuple(parameter.name for parameter in function.type_parameters)
    visible_type_parameters = (*enclosing_type_parameters, *parameter_names)
    type_parameters = tuple(
        parameter.declaration for parameter in function.type_parameters
    )
    parameters: list[Parameter] = []
    for parameter in function.parameters:
        annotation: TypeExpression = TypeName("Any")
        if parameter.annotation is not None:
            annotation = _adapt_type_expression(
                parameter.annotation,
                function.name,
                visible_type_parameters,
                aliases,
            )
        parameters.append(
            Parameter(
                name=parameter.name,
                annotation=annotation,
                kind=adapt_parameter_kind(parameter.kind),
                default="..." if parameter.has_default else None,
            )
        )
    return_type: TypeExpression = TypeName("Any")
    if function.returns is not None:
        return_type = _adapt_type_expression(
            function.returns,
            function.name,
            visible_type_parameters,
            aliases,
        )
    return FunctionDeclaration(
        name=function.name,
        parameters=tuple(parameters),
        return_type=return_type,
        type_parameters=type_parameters,
        is_async=function.is_async,
        decorators=function.decorators,
    )


@safe(exceptions=(AdaptationError,))
def adapt_type_expression(
    declaration: str,
    expression: SourceTypeExpression,
    type_parameters: tuple[str, ...],
    *,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> TypeExpression:
    return _adapt_type_expression(expression, declaration, type_parameters, aliases)


@singledispatch
def _adapt_type_expression(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression:
    raise AdaptationError(
        declaration,
        expression.source,
        f"unsupported type expression {type(expression).__name__}",
    )


@_adapt_type_expression.register
def _(
    expression: SchemaTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression:
    if len(expression.arguments) != 1:
        raise AdaptationError(
            declaration,
            expression.source,
            "Schema requires one type argument",
        )
    return _adapt_schema_type(
        expression.arguments[0],
        declaration,
        type_parameters,
        aliases,
    )


@_adapt_type_expression.register
def _(
    expression: RuntimeInputTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression:
    return RuntimeInputType()


@_adapt_type_expression.register
def _(
    expression: NameTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression:
    if expression.source in type_parameters:
        return TypeVariable(expression.source)
    return TypeName(expression.source)


@_adapt_type_expression.register
def _(
    expression: RawTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression:
    return TypeName(expression.source)


@_adapt_type_expression.register
def _(
    expression: UnionTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression:
    return UnionExpression(
        _adapt_type_expressions(
            expression.members,
            declaration,
            type_parameters,
            aliases,
        )
    )


@_adapt_type_expression.register
def _(
    expression: StarredTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression:
    return UnpackedType(
        _adapt_type_expression(
            expression.item,
            declaration,
            type_parameters,
            aliases,
        )
    )


@_adapt_type_expression.register
def _(
    expression: AppliedTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression:
    return TypeApplication(
        _adapt_type_expression(
            expression.constructor,
            declaration,
            type_parameters,
            aliases,
        ),
        _adapt_type_expressions(
            expression.arguments,
            declaration,
            type_parameters,
            aliases,
        ),
    )


@_adapt_type_expression.register
def _(
    expression: MarkerTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression:
    marker = _normalize_marker(declaration, expression)
    match marker:
        case ValueMarker():
            return MapValueType()
        case MapMarker(subject=subject, entries=entries):
            cases = tuple(
                MapCase(
                    _adapt_map_test(
                        entry.test,
                        declaration,
                        type_parameters,
                        aliases,
                    ),
                    _adapt_type_expression(
                        entry.output,
                        declaration,
                        type_parameters,
                        aliases,
                    ),
                )
                for entry in entries
                if isinstance(entry, CaseMarker)
            )
            default_entry = next(
                (entry for entry in entries if isinstance(entry, DefaultMarker)),
                None,
            )
            default = (
                TypeName("Never")
                if default_entry is None
                else _adapt_type_expression(
                    default_entry.output,
                    declaration,
                    type_parameters,
                    aliases,
                )
            )
            return MapType(
                _adapt_type_expression(
                    subject,
                    declaration,
                    type_parameters,
                    aliases,
                ),
                cases,
                default,
            )
        case EachMarker(item=item):
            return EachType(
                _adapt_type_expression(item, declaration, type_parameters, aliases)
            )
        case CollectMarker(item=item):
            return CollectType(
                _adapt_type_expression(item, declaration, type_parameters, aliases)
            )
        case _:
            raise AdaptationError(
                declaration,
                expression.source,
                f"unsupported marker {type(marker).__name__.removesuffix('Marker')}",
            )


@safe(exceptions=(AdaptationError,))
def adapt_predicate(
    declaration: str,
    expression: SourceTypeExpression,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> Predicate:
    return _adapt_predicate(expression, declaration, type_parameters, aliases)


def _adapt_map_test(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> TypeExpression | Predicate:
    if isinstance(expression, MarkerTypeExpression):
        marker = _normalize_marker(declaration, expression)
        if isinstance(
            marker,
            EqualMarker | AssignableMarker | AllMarker | AnyMarker | NotMarker,
        ):
            return _adapt_predicate(
                expression,
                declaration,
                type_parameters,
                aliases,
            )
    return _adapt_type_expression(
        expression,
        declaration,
        type_parameters,
        aliases,
    )


def _adapt_predicate(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> Predicate:
    if not isinstance(expression, MarkerTypeExpression):
        raise AdaptationError(
            declaration,
            expression.source,
            "condition must be a Typeforge predicate",
        )
    marker = _normalize_marker(declaration, expression)
    match marker:
        case EqualMarker(left=left, right=right):
            return EqualPredicate(
                _adapt_type_expression(left, declaration, type_parameters, aliases),
                _adapt_type_expression(right, declaration, type_parameters, aliases),
            )
        case AssignableMarker(left=left, right=right):
            return AssignablePredicate(
                _adapt_type_expression(left, declaration, type_parameters, aliases),
                _adapt_type_expression(right, declaration, type_parameters, aliases),
            )
        case AllMarker(items=items):
            return AllPredicate(
                tuple(
                    _adapt_predicate(item, declaration, type_parameters, aliases)
                    for item in items
                )
            )
        case AnyMarker(items=items):
            return AnyPredicate(
                tuple(
                    _adapt_predicate(item, declaration, type_parameters, aliases)
                    for item in items
                )
            )
        case NotMarker(item=item):
            return NotPredicate(
                _adapt_predicate(item, declaration, type_parameters, aliases)
            )
        case _:
            raise AdaptationError(
                declaration,
                expression.source,
                f"{type(marker).__name__.removesuffix('Marker')} is not a predicate",
            )


def _normalize_marker(
    declaration: str,
    expression: MarkerTypeExpression,
) -> NormalizedMarker:
    try:
        return normalize_marker(expression)
    except MarkerNormalizationError as error:
        raise AdaptationError(
            declaration,
            error.source,
            error.message,
        ) from error


def _adapt_type_expressions(
    expressions: tuple[SourceTypeExpression, ...],
    declaration: str,
    type_parameters: tuple[str, ...],
    aliases: tuple[SemanticRelationshipAlias, ...] = (),
) -> tuple[TypeExpression, ...]:
    return tuple(
        _adapt_type_expression(expression, declaration, type_parameters, aliases)
        for expression in expressions
    )


def adapt_parameter_kind(kind: SourceParameterKind) -> ParameterKind:
    return ParameterKind(kind.value)
