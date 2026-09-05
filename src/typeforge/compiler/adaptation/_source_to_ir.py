"""Adapt source syntax into lowering IR and expand semantic type relationships."""

from functools import singledispatch

from returns.result import Result, safe

from typeforge.compiler.adaptation._imports import annotation_contains_default_never
from typeforge.compiler.adaptation._legacy_schema import resolve_schema_type
from typeforge.compiler.adaptation._models import (
    AdaptationError,
    SemanticRelationshipAlias,
)
from typeforge.compiler.adaptation._records import materialize_records
from typeforge.compiler.record_materialization import RecordMaterializationError
from typeforge.compiler.source import (
    AllMarker,
    AnyMarker,
    AppliedTypeExpression,
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
    MarkerTypeExpression,
    NameTypeExpression,
    NormalizedMarker,
    NotMarker,
    OptionalFieldMarker,
    RawTypeExpression,
    ReadonlyFieldMarker,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceModule,
    SourceSpan,
    SourceTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
    ValueMarker,
    is_enriched,
    normalize_marker,
    schema_inner_expression,
)
from typeforge.compiler.source import (
    ClassDeclaration as SourceClass,
)
from typeforge.compiler.source import (
    FunctionDeclaration as SourceFunction,
)
from typeforge.compiler.source import (
    ParameterKind as SourceParameterKind,
)
from typeforge.compiler.source import (
    TypeAliasDeclaration as SourceTypeAlias,
)
from typeforge.compiler.stub_ir import (
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
    GeneratedElementOrigin,
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
    StubTypeExpression,
    TypeAliasDeclaration,
    TypeApplication,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    merge_imports,
    rewrite_type_children,
    substitute_type,
)

_ADAPTATION_ERRORS: tuple[type[AdaptationError | RecordMaterializationError], ...] = (
    AdaptationError,
    RecordMaterializationError,
)


@safe(exceptions=_ADAPTATION_ERRORS)
def adapt_source_module(
    module: SourceModule,
) -> StubModule:
    imports: tuple[ModuleImport, ...] = ()
    semantic_aliases = _collect_semantic_relationship_aliases(module.aliases)
    semantic_alias_names = {alias.name for alias in semantic_aliases}
    declarations: list[tuple[int, Declaration]] = []
    origins: list[GeneratedElementOrigin[SourceSpan]] = []
    for alias in module.aliases:
        if len(alias.qualified_name) != 1:
            continue

        lowered_alias = TypeAliasDeclaration(
            name=alias.name,
            value=_adapt_alias_fallback(
                declaration=alias.name,
                expression=alias.value,
                type_parameters=tuple(
                    parameter.name for parameter in alias.type_parameters
                ),
            ),
            type_parameters=tuple(
                parameter.declaration for parameter in alias.type_parameters
            ),
        )
        generated_alias = TypeAliasDeclaration(
            name=lowered_alias.name,
            value=expand_map_aliases(lowered_alias.value, semantic_aliases),
            type_parameters=lowered_alias.type_parameters,
        )
        declarations.append((alias.span.start.line, generated_alias))
        if alias.name in semantic_alias_names and isinstance(
            generated_alias.value, MapType
        ):
            origins.append(GeneratedElementOrigin(alias.span, generated_alias))

    for source_class in module.classes:
        declarations.append(
            (
                source_class.span.start.line,
                expand_class_map_aliases(_adapt_class(source_class), semantic_aliases),
            )
        )

    for function in module.functions:
        if len(function.qualified_name) != 1:
            continue

        generated_function = expand_function_map_aliases(
            _adapt_function(function), semantic_aliases
        )
        declarations.append(
            (
                function.span.start.line,
                generated_function,
            )
        )
        if is_enriched(function):
            origins.append(GeneratedElementOrigin(function.span, generated_function))

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
    ordered_origins = tuple(
        sorted(
            origins,
            key=lambda item: (item.origin.start.line, item.origin.start.column),
        )
    )
    return materialize_records(
        module,
        StubModule(module.path.stem, ordered, imports, ordered_origins),
    )


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

        semantic.append(SemanticRelationshipAlias(alias.name, parameter, relationship))

    return tuple(semantic)


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
                name=parameter.name,
                annotation=expand_map_aliases(parameter.annotation, aliases),
                kind=parameter.kind,
                default=parameter.default,
            )
            for parameter in declaration.parameters
        ),
        return_type=expand_map_aliases(declaration.return_type, aliases),
        type_parameters=declaration.type_parameters,
        is_async=declaration.is_async,
        decorators=declaration.decorators,
    )


def expand_map_aliases(
    expression: StubTypeExpression,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> StubTypeExpression:
    match expression:
        case SchemaType(item):
            return resolve_schema_type(expand_map_aliases(item, aliases))
        case TypeApplication(TypeName(name), (argument,)):
            alias = next((item for item in aliases if item.name == name), None)
            if alias is not None:
                return substitute_type(
                    alias.relationship,
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
) -> TypeAliasDeclaration:
    parameter_names = tuple(parameter.name for parameter in alias.type_parameters)
    type_parameters = tuple(
        parameter.declaration for parameter in alias.type_parameters
    )
    return TypeAliasDeclaration(
        alias.name,
        _adapt_alias_fallback(alias.name, alias.value, parameter_names),
        type_parameters,
    )


@safe(exceptions=(AdaptationError,))
def adapt_class(
    source_class: SourceClass,
) -> ClassDeclaration:
    return _adapt_class(source_class)


def _adapt_class(source_class: SourceClass) -> ClassDeclaration:
    parameter_names = tuple(
        parameter.name for parameter in source_class.type_parameters
    )
    bases = _adapt_type_expressions(
        source_class.bases, source_class.name, parameter_names
    )
    fields = tuple(
        ClassField(
            field.name,
            _adapt_type_expression(
                field.annotation, source_class.name, parameter_names
            ),
            "..." if field.has_default else None,
        )
        for field in source_class.fields
    )
    methods = tuple(
        _adapt_function(method, parameter_names) for method in source_class.methods
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
) -> StubTypeExpression:
    if not isinstance(expression, MarkerTypeExpression):
        return _adapt_type_expression(expression, declaration, type_parameters)

    marker = _normalize_marker(declaration, expression)
    match marker:
        case EachMarker(item=item):
            return _adapt_alias_fallback(declaration, item, type_parameters)

        case CollectMarker(item=item):
            return HomogeneousTuple(
                _adapt_alias_fallback(declaration, item, type_parameters)
            )

        case MapMarker():
            return _adapt_type_expression(expression, declaration, type_parameters)

        case MapFieldsMarker():
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
            return _adapt_alias_fallback(declaration, value, type_parameters)

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
) -> FunctionDeclaration:
    return _adapt_function(function, enclosing_type_parameters)


def _adapt_function(
    function: SourceFunction,
    enclosing_type_parameters: tuple[str, ...] = (),
) -> FunctionDeclaration:
    parameter_names = tuple(parameter.name for parameter in function.type_parameters)
    visible_type_parameters = (*enclosing_type_parameters, *parameter_names)
    type_parameters = tuple(
        parameter.declaration for parameter in function.type_parameters
    )
    parameters: list[Parameter] = []
    for parameter in function.parameters:
        annotation: StubTypeExpression = TypeName("Any")
        if parameter.annotation is not None:
            annotation = _adapt_type_expression(
                parameter.annotation,
                function.name,
                visible_type_parameters,
            )

        parameters.append(
            Parameter(
                name=parameter.name,
                annotation=annotation,
                kind=adapt_parameter_kind(parameter.kind),
                default="..." if parameter.has_default else None,
            )
        )

    return_type: StubTypeExpression = TypeName("Any")
    if function.returns is not None:
        return_type = _adapt_type_expression(
            function.returns,
            function.name,
            visible_type_parameters,
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
) -> StubTypeExpression:
    return _adapt_type_expression(expression, declaration, type_parameters)


@singledispatch
def _adapt_type_expression(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> StubTypeExpression:
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
) -> StubTypeExpression:
    if len(expression.arguments) != 1:
        raise AdaptationError(
            declaration,
            expression.source,
            "Schema requires one type argument",
        )

    return SchemaType(
        _adapt_type_expression(expression.arguments[0], declaration, type_parameters)
    )


@_adapt_type_expression.register
def _(
    expression: RuntimeInputTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> StubTypeExpression:
    return RuntimeInputType()


@_adapt_type_expression.register
def _(
    expression: NameTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> StubTypeExpression:
    if expression.source in type_parameters:
        return TypeVariable(expression.source)

    return TypeName(expression.source)


@_adapt_type_expression.register
def _(
    expression: RawTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> StubTypeExpression:
    return TypeName(expression.source)


@_adapt_type_expression.register
def _(
    expression: UnionTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> StubTypeExpression:
    return UnionExpression(
        _adapt_type_expressions(expression.members, declaration, type_parameters)
    )


@_adapt_type_expression.register
def _(
    expression: StarredTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> StubTypeExpression:
    return UnpackedType(
        _adapt_type_expression(expression.item, declaration, type_parameters)
    )


@_adapt_type_expression.register
def _(
    expression: AppliedTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> StubTypeExpression:
    return TypeApplication(
        _adapt_type_expression(expression.constructor, declaration, type_parameters),
        _adapt_type_expressions(expression.arguments, declaration, type_parameters),
    )


@_adapt_type_expression.register
def _(
    expression: MarkerTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> StubTypeExpression:
    marker = _normalize_marker(declaration, expression)
    match marker:
        case ValueMarker():
            return MapValueType()
        case MapMarker(subject=subject, entries=entries):
            cases = tuple(
                MapCase(
                    _adapt_map_test(entry.test, declaration, type_parameters),
                    _adapt_type_expression(entry.output, declaration, type_parameters),
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
                    default_entry.output, declaration, type_parameters
                )
            )
            return MapType(
                _adapt_type_expression(subject, declaration, type_parameters),
                cases,
                default,
            )
        case EachMarker(item=item):
            return EachType(_adapt_type_expression(item, declaration, type_parameters))
        case CollectMarker(item=item):
            return CollectType(
                _adapt_type_expression(item, declaration, type_parameters)
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
) -> Predicate:
    return _adapt_predicate(expression, declaration, type_parameters)


def _adapt_map_test(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> StubTypeExpression | Predicate:
    if isinstance(expression, MarkerTypeExpression):
        marker = _normalize_marker(declaration, expression)
        if isinstance(
            marker,
            EqualMarker | AssignableMarker | AllMarker | AnyMarker | NotMarker,
        ):
            return _adapt_predicate(expression, declaration, type_parameters)

    return _adapt_type_expression(expression, declaration, type_parameters)


def _adapt_predicate(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
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
                _adapt_type_expression(left, declaration, type_parameters),
                _adapt_type_expression(right, declaration, type_parameters),
            )
        case AssignableMarker(left=left, right=right):
            return AssignablePredicate(
                _adapt_type_expression(left, declaration, type_parameters),
                _adapt_type_expression(right, declaration, type_parameters),
            )
        case AllMarker(items=items):
            return AllPredicate(
                tuple(
                    _adapt_predicate(item, declaration, type_parameters)
                    for item in items
                )
            )
        case AnyMarker(items=items):
            return AnyPredicate(
                tuple(
                    _adapt_predicate(item, declaration, type_parameters)
                    for item in items
                )
            )
        case NotMarker(item=item):
            return NotPredicate(_adapt_predicate(item, declaration, type_parameters))
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
) -> tuple[StubTypeExpression, ...]:
    return tuple(
        _adapt_type_expression(expression, declaration, type_parameters)
        for expression in expressions
    )


def adapt_parameter_kind(kind: SourceParameterKind) -> ParameterKind:
    return ParameterKind(kind.value)
