"""Adapt source syntax into lowering IR and expand semantic type relationships."""

from dataclasses import replace
from functools import singledispatch

from typeforge.compiler.adaptation._imports import annotation_imports
from typeforge.compiler.adaptation._models import (
    AdaptationError,
    SemanticRelationshipAlias,
)
from typeforge.compiler.adaptation._records import materialize_records
from typeforge.compiler.adaptation._schema import adapt_schema_expression
from typeforge.compiler.record_materialization import (
    RecordMaterializationError,
    is_map_fields_alias,
)
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
    contains_marker,
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
    GeneratedElement,
    GeneratedElementOrigin,
    HomogeneousTuple,
    MapCase,
    MapType,
    MapValueType,
    NotPredicate,
    Parameter,
    ParameterKind,
    Predicate,
    RuntimeInputType,
    StubModule,
    StubTypeExpression,
    TypeAliasDeclaration,
    TypeApplication,
    TypeName,
    TypeRewriteObserver,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    rewrite_type_children,
    substitute_type,
    walk_module,
)
from typeforge.utils.error_handling import safe_result

_ADAPTATION_ERRORS: tuple[type[AdaptationError | RecordMaterializationError], ...] = (
    AdaptationError,
    RecordMaterializationError,
)


@safe_result(errors=_ADAPTATION_ERRORS)
def adapt_source_module(
    module: SourceModule,
) -> StubModule:
    # Record aliases retain their references until the materialization stage.
    schema_aliases = tuple(
        alias for alias in module.aliases if not is_map_fields_alias(alias)
    )
    origins: list[GeneratedElementOrigin[SourceSpan]] = []
    semantic_aliases = _collect_semantic_relationship_aliases(
        module.aliases, origins=origins, schema_aliases=schema_aliases
    )
    reusable_elements: list[GeneratedElement] = []
    declarations: list[tuple[int, Declaration]] = []

    def record_rewrite(
        original: StubTypeExpression, replacement: StubTypeExpression
    ) -> None:
        if original is not replacement:
            origins.extend(
                replace(item, generated=replacement)
                for item in tuple(origins)
                if item.generated is original
            )

    for alias in module.aliases:
        if len(alias.qualified_name) != 1:
            continue

        origin_count_before_alias = len(origins)
        lowered_alias = TypeAliasDeclaration(
            name=alias.name,
            value=_adapt_alias_fallback(
                declaration=alias.name,
                expression=alias.value,
                type_parameters=tuple(
                    parameter.name for parameter in alias.type_parameters
                ),
                origins=origins,
                schema_aliases=schema_aliases,
            ),
            type_parameters=tuple(
                parameter.declaration for parameter in alias.type_parameters
            ),
        )
        has_authored_transform = (
            contains_marker(alias.value) or len(origins) > origin_count_before_alias
        )
        generated_alias = replace(
            lowered_alias,
            value=expand_map_aliases(
                lowered_alias.value, semantic_aliases, on_rewrite=record_rewrite
            ),
        )
        declarations.append((alias.span.start.line, generated_alias))
        if has_authored_transform:
            origins.append(GeneratedElementOrigin(alias.span, generated_alias))
            relationship = next(
                (
                    item.relationship
                    for item in semantic_aliases
                    if item.name == alias.name
                ),
                None,
            )
            if relationship is not None:
                reusable_elements.append(relationship)
                origins.append(GeneratedElementOrigin(alias.span, relationship))

    for source_class in module.classes:
        generated_class = expand_class_map_aliases(
            _adapt_class(source_class, origins=origins, schema_aliases=schema_aliases),
            semantic_aliases,
            on_rewrite=record_rewrite,
        )
        declarations.append(
            (
                source_class.span.start.line,
                generated_class,
            )
        )
        origins.extend(
            GeneratedElementOrigin(authored.span, generated)
            for authored, generated in zip(
                source_class.methods, generated_class.methods, strict=True
            )
            if is_enriched(authored)
            or (
                isinstance(generated, FunctionDeclaration)
                and isinstance(generated.return_type, MapType)
            )
        )
        reusable_elements.extend(
            method
            for method in generated_class.methods
            if isinstance(method, FunctionDeclaration)
            and isinstance(method.return_type, MapType)
        )

    class_method_spans = {
        method.span
        for source_class in module.classes
        for method in source_class.methods
    }
    class_parameters = {
        declaration.name: tuple(
            parameter.name for parameter in declaration.type_parameters
        )
        for declaration in module.classes
    }
    for function in module.functions:
        if function.span in class_method_spans:
            continue

        generated_function = expand_function_map_aliases(
            _adapt_function(
                function,
                class_parameters.get(function.qualified_name[0], ())
                if len(function.qualified_name) == 2
                else (),
                origins=origins,
                schema_aliases=schema_aliases,
            ),
            semantic_aliases,
            on_rewrite=record_rewrite,
        )
        has_origin = is_enriched(function) or isinstance(
            generated_function.return_type, MapType
        )
        if len(function.qualified_name) > 1 and not has_origin:
            continue

        declarations.append(
            (
                function.span.start.line,
                generated_function,
            )
        )
        if has_origin:
            origins.append(GeneratedElementOrigin(function.span, generated_function))

        if isinstance(generated_function.return_type, MapType):
            reusable_elements.append(generated_function)

    # Schema roots keep authored parameter names and their own boundary identity,
    # even when semantic aliases reuse the same output node in other declarations.
    scopes: tuple[SourceClass | SourceFunction | SourceTypeAlias, ...] = (
        *module.classes,
        *module.functions,
        *module.aliases,
    )
    for boundary in _schema_boundaries(module):
        parameters = tuple(
            dict.fromkeys(
                parameter.name
                for declaration in scopes
                if declaration.span.start <= boundary.span.start <= declaration.span.end
                for parameter in declaration.type_parameters
            )
        )
        expression = adapt_schema_expression(
            boundary,
            schema_aliases,
            declaration="Schema",
            type_parameters=parameters,
        ).unwrap()
        reusable_elements.append(expression)
        origins.append(GeneratedElementOrigin(boundary.span, expression))

    ordered = tuple(
        declaration for _, declaration in sorted(declarations, key=lambda item: item[0])
    )
    adapted_module = StubModule(
        module.path.stem,
        ordered,
        annotation_imports(module),
        reusable_elements=tuple(reusable_elements),
    )
    current: dict[int, int] = {}
    for element in walk_module(adapted_module):
        current.setdefault(id(element), len(current))

    ordered_origins = tuple(
        sorted(
            {
                (item.origin, id(item.generated)): item
                for item in origins
                if id(item.generated) in current
            }.values(),
            key=lambda item: (item.origin.start, current[id(item.generated)]),
        )
    )
    return materialize_records(
        module,
        replace(adapted_module, origins=ordered_origins),
    )


def _collect_semantic_relationship_aliases(
    aliases: tuple[SourceTypeAlias, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
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
        relationship = _adapt_type_expression(
            value,
            alias.name,
            (parameter,),
            origins=origins,
            schema_aliases=schema_aliases,
        )
        if not isinstance(relationship, MapType):
            raise AssertionError("relationship adaptation produced a plain type")

        if origins is not None and isinstance(alias.value, SchemaTypeExpression):
            origins.append(GeneratedElementOrigin(alias.value.span, relationship))

        semantic.append(SemanticRelationshipAlias(alias.name, parameter, relationship))

    return tuple(semantic)


def expand_class_map_aliases(
    declaration: ClassDeclaration,
    aliases: tuple[SemanticRelationshipAlias, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> ClassDeclaration:
    return replace(
        declaration,
        bases=tuple(
            expand_map_aliases(base, aliases, on_rewrite=on_rewrite)
            for base in declaration.bases
        ),
        fields=tuple(
            replace(
                field,
                annotation=expand_map_aliases(
                    field.annotation, aliases, on_rewrite=on_rewrite
                ),
            )
            for field in declaration.fields
        ),
        methods=tuple(
            expand_function_map_aliases(method, aliases, on_rewrite=on_rewrite)
            if isinstance(method, FunctionDeclaration)
            else method
            for method in declaration.methods
        ),
    )


def expand_function_map_aliases(
    declaration: FunctionDeclaration,
    aliases: tuple[SemanticRelationshipAlias, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> FunctionDeclaration:
    return replace(
        declaration,
        parameters=tuple(
            replace(
                parameter,
                annotation=expand_map_aliases(
                    parameter.annotation, aliases, on_rewrite=on_rewrite
                ),
            )
            for parameter in declaration.parameters
        ),
        return_type=expand_map_aliases(
            declaration.return_type, aliases, on_rewrite=on_rewrite
        ),
    )


def expand_map_aliases(
    expression: StubTypeExpression,
    aliases: tuple[SemanticRelationshipAlias, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    replacement = _expand_map_aliases(expression, aliases, on_rewrite)
    if on_rewrite is not None:
        on_rewrite(expression, replacement)

    return replacement


def _expand_map_aliases(
    expression: StubTypeExpression,
    aliases: tuple[SemanticRelationshipAlias, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    match expression:
        case TypeApplication(TypeName(name), (argument,)):
            alias = next((item for item in aliases if item.name == name), None)
            if alias is not None:
                return substitute_type(
                    alias.relationship,
                    alias.parameter,
                    expand_map_aliases(argument, aliases, on_rewrite=on_rewrite),
                    on_rewrite=on_rewrite,
                )

        case _:
            pass

    return rewrite_type_children(
        expression,
        lambda child: expand_map_aliases(child, aliases, on_rewrite=on_rewrite),
    )


def _adapt_class(
    source_class: SourceClass,
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> ClassDeclaration:
    parameter_names = tuple(
        parameter.name for parameter in source_class.type_parameters
    )
    bases = _adapt_type_expressions(
        source_class.bases,
        source_class.name,
        parameter_names,
        origins=origins,
        schema_aliases=schema_aliases,
    )
    fields = tuple(
        ClassField(
            field.name,
            _adapt_type_expression(
                field.annotation,
                source_class.name,
                parameter_names,
                origins=origins,
                schema_aliases=schema_aliases,
            ),
            "..." if field.has_default else None,
        )
        for field in source_class.fields
    )
    methods = tuple(
        _adapt_function(
            method, parameter_names, origins=origins, schema_aliases=schema_aliases
        )
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
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> StubTypeExpression:
    if not isinstance(expression, MarkerTypeExpression):
        return _adapt_type_expression(
            expression,
            declaration,
            type_parameters,
            origins=origins,
            schema_aliases=schema_aliases,
        )

    marker = _normalize_marker(declaration, expression)
    match marker:
        case EachMarker(item=item):
            return _adapt_alias_fallback(
                declaration,
                item,
                type_parameters,
                origins=origins,
                schema_aliases=schema_aliases,
            )

        case CollectMarker(item=item):
            return HomogeneousTuple(
                _adapt_alias_fallback(
                    declaration,
                    item,
                    type_parameters,
                    origins=origins,
                    schema_aliases=schema_aliases,
                )
            )

        case MapMarker():
            return _adapt_type_expression(
                expression,
                declaration,
                type_parameters,
                origins=origins,
                schema_aliases=schema_aliases,
            )

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
            return _adapt_alias_fallback(
                declaration,
                value,
                type_parameters,
                origins=origins,
                schema_aliases=schema_aliases,
            )

        case DropMarker():
            return TypeName("Never")

        case KeyMarker():
            return TypeName("str")

        case ValueMarker():
            return TypeName("object")


def _adapt_function(
    function: SourceFunction,
    enclosing_type_parameters: tuple[str, ...] = (),
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
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
                origins=origins,
                schema_aliases=schema_aliases,
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
            origins=origins,
            schema_aliases=schema_aliases,
        )

    return FunctionDeclaration(
        name=function.name,
        parameters=tuple(parameters),
        return_type=return_type,
        type_parameters=type_parameters,
        is_async=function.is_async,
        decorators=function.decorators,
    )


@singledispatch
def _adapt_type_expression(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
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
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> StubTypeExpression:
    return adapt_schema_expression(
        expression,
        schema_aliases,
        declaration=declaration,
        type_parameters=type_parameters,
        preserve_type_variables=True,
        origins=origins,
    ).unwrap()


@_adapt_type_expression.register
def _(
    expression: RuntimeInputTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> StubTypeExpression:
    return RuntimeInputType()


@_adapt_type_expression.register
def _(
    expression: NameTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> StubTypeExpression:
    if expression.source in type_parameters:
        return TypeVariable(expression.source)

    return TypeName(expression.source)


@_adapt_type_expression.register
def _(
    expression: RawTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> StubTypeExpression:
    return TypeName(expression.source)


@_adapt_type_expression.register
def _(
    expression: UnionTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> StubTypeExpression:
    return UnionExpression(
        _adapt_type_expressions(
            expression.members,
            declaration,
            type_parameters,
            origins=origins,
            schema_aliases=schema_aliases,
        )
    )


@_adapt_type_expression.register
def _(
    expression: StarredTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> StubTypeExpression:
    return UnpackedType(
        _adapt_type_expression(
            expression.item,
            declaration,
            type_parameters,
            origins=origins,
            schema_aliases=schema_aliases,
        )
    )


@_adapt_type_expression.register
def _(
    expression: AppliedTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> StubTypeExpression:
    return TypeApplication(
        _adapt_type_expression(
            expression.constructor,
            declaration,
            type_parameters,
            origins=origins,
            schema_aliases=schema_aliases,
        ),
        _adapt_type_expressions(
            expression.arguments,
            declaration,
            type_parameters,
            origins=origins,
            schema_aliases=schema_aliases,
        ),
    )


@_adapt_type_expression.register
def _(
    expression: MarkerTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> StubTypeExpression:
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
                        origins=origins,
                        schema_aliases=schema_aliases,
                    ),
                    _adapt_type_expression(
                        entry.output,
                        declaration,
                        type_parameters,
                        origins=origins,
                        schema_aliases=schema_aliases,
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
                    origins=origins,
                    schema_aliases=schema_aliases,
                )
            )
            return MapType(
                _adapt_type_expression(
                    subject,
                    declaration,
                    type_parameters,
                    origins=origins,
                    schema_aliases=schema_aliases,
                ),
                cases,
                default,
            )
        case EachMarker(item=item):
            return EachType(
                _adapt_type_expression(
                    item,
                    declaration,
                    type_parameters,
                    origins=origins,
                    schema_aliases=schema_aliases,
                )
            )
        case CollectMarker(item=item):
            return CollectType(
                _adapt_type_expression(
                    item,
                    declaration,
                    type_parameters,
                    origins=origins,
                    schema_aliases=schema_aliases,
                )
            )
        case _:
            raise AdaptationError(
                declaration,
                expression.source,
                f"unsupported marker {type(marker).__name__.removesuffix('Marker')}",
            )


def _adapt_map_test(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> StubTypeExpression | Predicate:
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
                origins=origins,
                schema_aliases=schema_aliases,
            )

    return _adapt_type_expression(
        expression,
        declaration,
        type_parameters,
        origins=origins,
        schema_aliases=schema_aliases,
    )


def _adapt_predicate(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
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
                _adapt_type_expression(
                    left,
                    declaration,
                    type_parameters,
                    origins=origins,
                    schema_aliases=schema_aliases,
                ),
                _adapt_type_expression(
                    right,
                    declaration,
                    type_parameters,
                    origins=origins,
                    schema_aliases=schema_aliases,
                ),
            )
        case AssignableMarker(left=left, right=right):
            return AssignablePredicate(
                _adapt_type_expression(
                    left,
                    declaration,
                    type_parameters,
                    origins=origins,
                    schema_aliases=schema_aliases,
                ),
                _adapt_type_expression(
                    right,
                    declaration,
                    type_parameters,
                    origins=origins,
                    schema_aliases=schema_aliases,
                ),
            )
        case AllMarker(items=items):
            return AllPredicate(
                tuple(
                    _adapt_predicate(
                        item,
                        declaration,
                        type_parameters,
                        origins=origins,
                        schema_aliases=schema_aliases,
                    )
                    for item in items
                )
            )
        case AnyMarker(items=items):
            return AnyPredicate(
                tuple(
                    _adapt_predicate(
                        item,
                        declaration,
                        type_parameters,
                        origins=origins,
                        schema_aliases=schema_aliases,
                    )
                    for item in items
                )
            )
        case NotMarker(item=item):
            return NotPredicate(
                _adapt_predicate(
                    item,
                    declaration,
                    type_parameters,
                    origins=origins,
                    schema_aliases=schema_aliases,
                )
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
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    schema_aliases: tuple[SourceTypeAlias, ...],
) -> tuple[StubTypeExpression, ...]:
    return tuple(
        _adapt_type_expression(
            expression,
            declaration,
            type_parameters,
            origins=origins,
            schema_aliases=schema_aliases,
        )
        for expression in expressions
    )


def adapt_parameter_kind(kind: SourceParameterKind) -> ParameterKind:
    return ParameterKind(kind.value)


def _schema_boundaries(module: SourceModule) -> tuple[SchemaTypeExpression, ...]:
    alias_spans = {alias.span for alias in module.aliases}
    expressions = (
        *(
            annotation
            for function in module.functions
            for annotation in (
                *(parameter.annotation for parameter in function.parameters),
                function.returns,
            )
            if annotation is not None
        ),
        *(
            field.annotation
            for declaration in module.typed_dicts
            for field in declaration.fields
        ),
        *(base for declaration in module.classes for base in declaration.bases),
        *(
            field.annotation
            for declaration in module.classes
            for field in declaration.fields
        ),
        *(
            annotation
            for declaration in module.classes
            for method in declaration.methods
            for annotation in (
                *(parameter.annotation for parameter in method.parameters),
                method.returns,
            )
            if annotation is not None
        ),
    )
    boundaries: dict[SourceSpan, SchemaTypeExpression] = {}
    for expression in expressions:
        for boundary in _outer_schema_boundaries(expression):
            if boundary.span in alias_spans:
                continue

            boundaries[boundary.span] = boundary

    return tuple(boundaries.values())


def _outer_schema_boundaries(
    expression: SourceTypeExpression,
) -> tuple[SchemaTypeExpression, ...]:
    if isinstance(expression, SchemaTypeExpression):
        return (expression,)

    if isinstance(expression, AppliedTypeExpression):
        children = (expression.constructor, *expression.arguments)
    elif isinstance(expression, UnionTypeExpression):
        children = expression.members
    elif isinstance(expression, StarredTypeExpression):
        children = (expression.item,)
    elif isinstance(expression, MarkerTypeExpression):
        children = expression.arguments
    else:
        children = ()

    return tuple(
        boundary for child in children for boundary in _outer_schema_boundaries(child)
    )
