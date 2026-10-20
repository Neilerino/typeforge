"""Adapt source annotation expressions at the source-to-stub boundary."""

from functools import singledispatch

from returns.result import Failure

from typeforge.compiler.adaptation._context import (
    SourceTypeContext,
)
from typeforge.compiler.adaptation._models import (
    AdaptationError,
)
from typeforge.compiler.adaptation._schema import adapt_schema_expression
from typeforge.compiler.adaptation._schema_aliases import expand_schema_aliases
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
    EachMarker,
    EqualMarker,
    MapMarker,
    MarkerNormalizationError,
    MarkerTypeExpression,
    NameTypeExpression,
    NormalizedMarker,
    NotMarker,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceSpan,
    SourceTypeExpression,
    StarredTypeExpression,
    UnionTypeExpression,
    ValueMarker,
    normalize_marker,
)
from typeforge.compiler.stub_ir import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    CaptureType,
    CollectType,
    EachType,
    EqualPredicate,
    GeneratedElementOrigin,
    MapCase,
    MapType,
    NotPredicate,
    Predicate,
    RuntimeInputType,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
)


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


def resolve_type_function_application(
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


@singledispatch
def adapt_type_expression(
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


@adapt_type_expression.register
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


@adapt_type_expression.register
def _(
    expression: RuntimeInputTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    return RuntimeInputType()


@adapt_type_expression.register
def _(
    expression: NameTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    if _is_type_function_application(expression, type_context):
        return resolve_type_function_application(
            expression, declaration, type_parameters, type_context, origins
        )

    expanded = expand_schema_aliases(
        expression, type_context.aliases, declaration=declaration, predicates_only=True
    ).unwrap()
    if isinstance(expanded, MarkerTypeExpression):
        return adapt_type_expression(
            expanded,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )

    if expression.source in type_parameters:
        return TypeVariable(expression.source)

    return TypeName(expression.source)


@adapt_type_expression.register
def _(
    expression: CaptureTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> CaptureType:
    return CaptureType(lower_capture_reference(expression).symbol)


@adapt_type_expression.register
def _(
    expression: RawTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    return TypeName(expression.source)


@adapt_type_expression.register
def _(
    expression: UnionTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    return UnionExpression(
        adapt_type_expressions(
            expression.members,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )
    )


@adapt_type_expression.register
def _(
    expression: StarredTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    return UnpackedType(
        adapt_type_expression(
            expression.item,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )
    )


@adapt_type_expression.register
def _(
    expression: AppliedTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> StubTypeExpression:
    if _is_type_function_application(expression, type_context):
        return resolve_type_function_application(
            expression, declaration, type_parameters, type_context, origins
        )

    expanded = expand_schema_aliases(
        expression, type_context.aliases, declaration=declaration, predicates_only=True
    ).unwrap()
    if isinstance(expanded, MarkerTypeExpression):
        return adapt_type_expression(
            expanded,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )

    return TypeApplication(
        adapt_type_expression(
            expression.constructor,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        ),
        adapt_type_expressions(
            expression.arguments,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        ),
    )


@adapt_type_expression.register
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
    marker = normalize_adaptation_marker(declaration, expression)
    match marker:
        case ValueMarker():
            raise AdaptationError(
                declaration,
                expression.source,
                "Value is a field reference; declare Capture for structural matching",
            )
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
                    adapt_type_expression(
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
                else adapt_type_expression(
                    default_entry.output,
                    declaration,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
                )
            )
            return MapType(
                adapt_type_expression(
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
                adapt_type_expression(
                    item,
                    declaration,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
                )
            )
        case CollectMarker(item=item):
            return CollectType(
                adapt_type_expression(
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
        marker = normalize_adaptation_marker(declaration, expression)
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

    return adapt_type_expression(
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

    marker = normalize_adaptation_marker(declaration, expression)
    match marker:
        case EqualMarker(left=left, right=right):
            return EqualPredicate(
                adapt_type_expression(
                    left,
                    declaration,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
                ),
                adapt_type_expression(
                    right,
                    declaration,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
                ),
            )
        case AssignableMarker(left=left, right=right):
            return AssignablePredicate(
                adapt_type_expression(
                    left,
                    declaration,
                    type_parameters,
                    origins=origins,
                    type_context=type_context,
                ),
                adapt_type_expression(
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


def normalize_adaptation_marker(
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


def adapt_type_expressions(
    expressions: tuple[SourceTypeExpression, ...],
    declaration: str,
    type_parameters: tuple[str, ...],
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
    *,
    type_context: SourceTypeContext,
) -> tuple[StubTypeExpression, ...]:
    return tuple(
        adapt_type_expression(
            expression,
            declaration,
            type_parameters,
            origins=origins,
            type_context=type_context,
        )
        for expression in expressions
    )
