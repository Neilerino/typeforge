"""Adapt source syntax into lowering IR and expand semantic type relationships."""

from dataclasses import replace
from functools import singledispatch

from returns.result import Failure

from typeforge.compiler.adaptation._context import (
    SourceTypeContext,
    class_type_environment,
)
from typeforge.compiler.adaptation._imports import annotation_imports
from typeforge.compiler.adaptation._models import (
    AdaptationError,
    SemanticRelationshipAlias,
)
from typeforge.compiler.adaptation._records import materialize_records
from typeforge.compiler.adaptation._schema import adapt_schema_expression
from typeforge.compiler.adaptation._schema_aliases import expand_schema_aliases
from typeforge.compiler.record_materialization import (
    RecordMaterializationError,
    is_record_alias,
)
from typeforge.compiler.semantic_adapter import lower_capture_reference
from typeforge.compiler.source import (
    AllMarker,
    AnyMarker,
    AppliedTypeExpression,
    AssignableMarker,
    CaptureTypeExpression,
    CaseMarker,
    CollectMarker,
    DefaultMarker,
    DropMarker,
    EachMarker,
    EqualMarker,
    MapMarker,
    MarkerKind,
    MarkerNormalizationError,
    MarkerTypeExpression,
    NameTypeExpression,
    NormalizedMarker,
    NotMarker,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceModule,
    SourceSpan,
    SourceTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
    bind_map_selector,
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
    CaptureType,
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
    module = _expand_type_function_templates(module)
    # Record aliases retain their references until the materialization stage.
    type_context = SourceTypeContext(
        aliases=tuple(alias for alias in module.aliases if not is_record_alias(alias)),
        types=class_type_environment(module),
    )
    origins: list[GeneratedElementOrigin[SourceSpan]] = []
    semantic_aliases = _collect_semantic_relationship_aliases(
        module.aliases, origins=origins, type_context=type_context
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
        parameters = tuple(parameter.name for parameter in alias.type_parameters)
        value: StubTypeExpression
        if is_record_alias(alias):
            # Record templates are materialized through the family-aware stage.
            value = TypeName("object")
        elif alias.is_type_function:
            value = _resolve_type_function_application(
                alias.value,
                alias.name,
                parameters,
                type_context,
                origins,
                unresolved_capture_bound=bool(parameters),
            )
        else:
            value = _adapt_alias_fallback(
                declaration=alias.name,
                expression=alias.value,
                type_parameters=parameters,
                origins=origins,
                type_context=type_context,
            )

        lowered_alias = TypeAliasDeclaration(
            name=alias.name,
            value=value,
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
            _adapt_class(source_class, origins=origins, type_context=type_context),
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
                type_context=type_context,
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

    # Annotation roots retain their authored span and independent identity so
    # overlays can replace them without losing callable verification contracts.
    scopes: tuple[SourceClass | SourceFunction | SourceTypeAlias, ...] = (
        *module.classes,
        *module.functions,
        *module.aliases,
    )
    for boundary in _annotation_boundaries(module):
        parameters = tuple(
            dict.fromkeys(
                parameter.name
                for declaration in scopes
                if declaration.span.start <= boundary.span.start <= declaration.span.end
                for parameter in declaration.type_parameters
            )
        )
        if isinstance(boundary, SchemaTypeExpression):
            expression = adapt_schema_expression(
                boundary,
                type_context.aliases,
                environment=type_context.types,
                declaration="Schema",
                type_parameters=parameters,
            ).unwrap()
        else:
            expression = _adapt_type_expression(
                boundary,
                "annotation",
                parameters,
                type_context=type_context,
            )
            expression = expand_map_aliases(expression, semantic_aliases)

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


def _expand_type_function_templates(module: SourceModule) -> SourceModule:
    """Resolve lexical aliases before outer parameters or record classification."""
    aliases = tuple(
        replace(
            alias,
            value=expand_schema_aliases(
                alias.value, alias.local_aliases, declaration=alias.name
            ).unwrap(),
        )
        if alias.is_type_function
        else alias
        for alias in module.aliases
    )
    expanded: list[SourceTypeAlias] = []
    for alias in aliases:
        if not alias.is_type_function:
            expanded.append(alias)
            continue

        value = expand_schema_aliases(
            alias.value, aliases, declaration=alias.name
        ).unwrap()
        expanded.append(replace(alias, value=value))

    return replace(module, aliases=tuple(expanded))


def _is_type_function_application(
    expression: NameTypeExpression | AppliedTypeExpression,
    type_context: SourceTypeContext,
) -> bool:
    name = (
        expression.constructor
        if isinstance(expression, AppliedTypeExpression)
        else expression
    )
    return isinstance(name, NameTypeExpression) and any(
        alias.is_type_function and alias.qualified_name == name.name
        for alias in type_context.aliases
    )


def _resolve_type_function_application(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    type_context: SourceTypeContext,
    origins: list[GeneratedElementOrigin[SourceSpan]] | None,
    *,
    unresolved_capture_bound: bool = False,
) -> StubTypeExpression:
    boundary = SchemaTypeExpression(expression.source, expression.span, (expression,))
    parameter_names = {(name,) for name in type_parameters}
    aliases = tuple(
        alias
        for alias in type_context.aliases
        if alias.qualified_name not in parameter_names
    )
    result = adapt_schema_expression(
        boundary,
        aliases,
        declaration=declaration,
        environment=type_context.types,
        type_parameters=type_parameters,
        preserve_type_variables=True,
        origins=origins,
    )
    if (
        unresolved_capture_bound
        and isinstance(result, Failure)
        and result.failure().unresolved_capture is not None
    ):
        # A declaration may expose a bound without inspecting unknown arguments.
        # Concrete applications still evaluate the retained source template.
        return TypeName("object")

    return result.unwrap()


def _collect_semantic_relationship_aliases(
    aliases: tuple[SourceTypeAlias, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> tuple[SemanticRelationshipAlias, ...]:
    semantic: list[SemanticRelationshipAlias] = []
    for alias in aliases:
        if alias.is_type_function:
            continue

        value = schema_inner_expression(
            expand_schema_aliases(
                alias.value,
                type_context.aliases,
                declaration=alias.name,
                predicates_only=True,
            ).unwrap()
        )
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
            type_context=type_context,
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
    type_context: SourceTypeContext,
) -> ClassDeclaration:
    parameter_names = tuple(
        parameter.name for parameter in source_class.type_parameters
    )
    bases = _adapt_type_expressions(
        source_class.bases,
        source_class.name,
        parameter_names,
        origins=origins,
        type_context=type_context,
    )
    fields = tuple(
        ClassField(
            field.name,
            _adapt_type_expression(
                field.annotation,
                source_class.name,
                parameter_names,
                origins=origins,
                type_context=type_context,
            ),
            "..." if field.has_default else None,
        )
        for field in source_class.fields
    )
    methods = tuple(
        _adapt_function(
            method, parameter_names, origins=origins, type_context=type_context
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
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    expression = expand_schema_aliases(
        expression, type_context.aliases, declaration=declaration, predicates_only=True
    ).unwrap()
    if isinstance(expression, MarkerTypeExpression) and expression.marker in {
        MarkerKind.EQUAL,
        MarkerKind.ASSIGNABLE,
        MarkerKind.ALL,
        MarkerKind.ANY,
        MarkerKind.NOT,
    }:
        # Declaring an unbound predicate is valid; validate its eventual binary
        # shape without assigning a consuming Map subject to the authored alias.
        try:
            normalized = bind_map_selector(
                expression,
                NameTypeExpression("object", expression.span, ("object",), None),
            )
        except MarkerNormalizationError as error:
            raise AdaptationError(declaration, error.source, error.message) from error

        assert isinstance(normalized, MarkerTypeExpression)
        expression = normalized

    if not isinstance(expression, MarkerTypeExpression):
        return _adapt_type_expression(
            expression,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )

    marker = _normalize_marker(declaration, expression)
    match marker:
        case EachMarker(item=item):
            return _adapt_alias_fallback(
                declaration,
                item,
                type_parameters,
                origins=origins,
                type_context=type_context,
            )

        case CollectMarker(item=item):
            return HomogeneousTuple(
                _adapt_alias_fallback(
                    declaration,
                    item,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
                )
            )

        case MapMarker():
            return _adapt_type_expression(
                expression,
                declaration,
                type_parameters,
                origins=origins,
                type_context=type_context,
            )

        case (
            AssignableMarker() | EqualMarker() | AllMarker() | AnyMarker() | NotMarker()
        ):
            return TypeName("bool")

        case CaseMarker(output=value) | DefaultMarker(output=value):
            return _adapt_alias_fallback(
                declaration,
                value,
                type_parameters,
                origins=origins,
                type_context=type_context,
            )

        case DropMarker():
            return TypeName("Never")


def _adapt_function(
    function: SourceFunction,
    enclosing_type_parameters: tuple[str, ...] = (),
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
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
                type_context=type_context,
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
            type_context=type_context,
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
    type_context: SourceTypeContext,
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
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    return adapt_schema_expression(
        expression,
        type_context.aliases,
        environment=type_context.types,
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
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    return RuntimeInputType()


@_adapt_type_expression.register
def _(
    expression: NameTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    if _is_type_function_application(expression, type_context):
        return _resolve_type_function_application(
            expression, declaration, type_parameters, type_context, origins
        )

    expanded = expand_schema_aliases(
        expression, type_context.aliases, declaration=declaration, predicates_only=True
    ).unwrap()
    if isinstance(expanded, MarkerTypeExpression):
        return _adapt_type_expression(
            expanded,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )

    if expression.source in type_parameters:
        return TypeVariable(expression.source)

    return TypeName(expression.source)


@_adapt_type_expression.register
def _(
    expression: CaptureTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> CaptureType:
    return CaptureType(lower_capture_reference(expression).symbol)


@_adapt_type_expression.register
def _(
    expression: RawTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    return TypeName(expression.source)


@_adapt_type_expression.register
def _(
    expression: UnionTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    return UnionExpression(
        _adapt_type_expressions(
            expression.members,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )
    )


@_adapt_type_expression.register
def _(
    expression: StarredTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    return UnpackedType(
        _adapt_type_expression(
            expression.item,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )
    )


@_adapt_type_expression.register
def _(
    expression: AppliedTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    if _is_type_function_application(expression, type_context):
        return _resolve_type_function_application(
            expression, declaration, type_parameters, type_context, origins
        )

    expanded = expand_schema_aliases(
        expression, type_context.aliases, declaration=declaration, predicates_only=True
    ).unwrap()
    if isinstance(expanded, MarkerTypeExpression):
        return _adapt_type_expression(
            expanded,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )

    return TypeApplication(
        _adapt_type_expression(
            expression.constructor,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        ),
        _adapt_type_expressions(
            expression.arguments,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        ),
    )


@_adapt_type_expression.register
def _(
    expression: MarkerTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    expanded = expand_schema_aliases(
        expression, type_context.aliases, declaration=declaration, predicates_only=True
    ).unwrap()
    assert isinstance(expanded, MarkerTypeExpression)
    expression = expanded
    marker = _normalize_marker(declaration, expression)
    match marker:
        case MapMarker(subject=subject, entries=entries):
            cases = tuple(
                MapCase(
                    _adapt_map_test(
                        entry.test,
                        declaration,
                        type_parameters,
                        origins=origins,
                        type_context=type_context,
                    ),
                    _adapt_type_expression(
                        entry.output,
                        declaration,
                        type_parameters,
                        origins=origins,
                        type_context=type_context,
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
                    type_context=type_context,
                )
            )
            return MapType(
                _adapt_type_expression(
                    subject,
                    declaration,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
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
                    type_context=type_context,
                )
            )
        case CollectMarker(item=item):
            return CollectType(
                _adapt_type_expression(
                    item,
                    declaration,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
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
    type_context: SourceTypeContext,
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
                type_context=type_context,
            )

    return _adapt_type_expression(
        expression,
        declaration,
        type_parameters,
        origins=origins,
        type_context=type_context,
    )


def _adapt_predicate(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
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
                    type_context=type_context,
                ),
                _adapt_type_expression(
                    right,
                    declaration,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
                ),
            )
        case AssignableMarker(left=left, right=right):
            return AssignablePredicate(
                _adapt_type_expression(
                    left,
                    declaration,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
                ),
                _adapt_type_expression(
                    right,
                    declaration,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
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
                        type_context=type_context,
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
                        type_context=type_context,
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
                    type_context=type_context,
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
    type_context: SourceTypeContext,
) -> tuple[StubTypeExpression, ...]:
    return tuple(
        _adapt_type_expression(
            expression,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )
        for expression in expressions
    )


def adapt_parameter_kind(kind: SourceParameterKind) -> ParameterKind:
    return ParameterKind(kind.value)


def _annotation_boundaries(
    module: SourceModule,
) -> tuple[SchemaTypeExpression | MarkerTypeExpression, ...]:
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
        *module.variable_annotations,
    )
    boundaries: dict[SourceSpan, SchemaTypeExpression | MarkerTypeExpression] = {}
    for expression in expressions:
        for boundary in _outer_annotation_boundaries(expression):
            if boundary.span in alias_spans:
                continue

            boundaries[boundary.span] = boundary

    return tuple(boundaries.values())


def _outer_annotation_boundaries(
    expression: SourceTypeExpression,
    *,
    inside_map: bool = False,
) -> tuple[SchemaTypeExpression | MarkerTypeExpression, ...]:
    if isinstance(expression, SchemaTypeExpression):
        return (expression,)

    mapping = (
        expression
        if isinstance(expression, MarkerTypeExpression)
        and expression.marker is MarkerKind.MAP
        else None
    )

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

    boundaries = tuple(
        boundary
        for child in children
        for boundary in _outer_annotation_boundaries(
            child, inside_map=inside_map or mapping is not None
        )
    )
    if mapping is not None and not inside_map:
        return (*boundaries, mapping)

    return boundaries
