"""Adapt authored schema boundaries through shared semantic evaluation."""

from dataclasses import dataclass, replace
from typing import Literal

from returns.result import Result, Success

from typeforge.compiler.adaptation._models import AdaptationError
from typeforge.compiler.adaptation._schema_aliases import expand_schema_aliases
from typeforge.compiler.semantic_adapter import (
    COMPILER_TYPE_SYSTEM,
    NamedType,
    ParameterizedType,
    SemanticEnvironment,
    SemanticLoweringError,
    StaticType,
    UnionType,
    UnpackedType,
    VariadicType,
    lower_semantic_expression,
    static_type_expression,
)
from typeforge.compiler.source import (
    AppliedTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    SchemaTypeExpression,
    SourceSpan,
    SourceTypeExpression,
    StarredTypeExpression,
    TypeAliasDeclaration,
    UnionTypeExpression,
)
from typeforge.compiler.stub_ir import (
    GeneratedElementOrigin,
    StubTypeExpression,
    walk_type,
)
from typeforge.semantics import (
    DeferredMap,
    ExpectedRecordSemanticError,
    ExpectedTypeSemanticError,
    IndeterminateType,
    MapNoMatch,
    ResolvedType,
    SemanticIssue,
    TypeSymbol,
    UnresolvedCaptureSemanticError,
    UnresolvedType,
    evaluate,
)
from typeforge.utils.error_handling import safe_result

_SCHEMA_ERRORS: tuple[
    type[
        AdaptationError | SemanticLoweringError | SemanticIssue | MapNoMatch[StaticType]
    ],
    ...,
] = (AdaptationError, SemanticLoweringError, SemanticIssue, MapNoMatch)


def adapt_schema_expression(
    expression: SchemaTypeExpression,
    aliases: tuple[TypeAliasDeclaration, ...],
    *,
    declaration: str,
    environment: SemanticEnvironment = (),
    type_parameters: tuple[str, ...] = (),
    preserve_type_variables: bool = False,
    never_name: str = "Never",
    origins: list[GeneratedElementOrigin[SourceSpan]] | None = None,
) -> Result[StubTypeExpression, AdaptationError]:
    """Expand source aliases, evaluate shared meaning, and emit a fresh typing root."""
    environment = (
        *environment,
        *(
            (
                name,
                UnresolvedType[StaticType](
                    NamedType(name),
                    TypeSymbol((str(expression.span.path), declaration), name),
                ),
            )
            for name in type_parameters
        ),
    )
    adapt_safely = safe_result(errors=_SCHEMA_ERRORS)(_adapt_schema_expression)
    staged_origins: list[GeneratedElementOrigin[SourceSpan]] = []
    result = adapt_safely(
        expression,
        aliases,
        declaration,
        environment,
        never_name,
        staged_origins,
        type_parameters if preserve_type_variables else (),
    ).alt(lambda error: _schema_adaptation_error(error, expression, declaration))
    if isinstance(result, Success) and origins is not None:
        origins.extend(staged_origins)

    return result


def _schema_adaptation_error(
    error: AdaptationError
    | SemanticLoweringError
    | SemanticIssue
    | MapNoMatch[StaticType],
    expression: SchemaTypeExpression,
    declaration: str,
) -> AdaptationError:
    if isinstance(error, AdaptationError):
        return error

    if isinstance(error, ExpectedRecordSemanticError):
        return AdaptationError(
            declaration, expression.source, "Record requires a supported record type"
        )

    if isinstance(error, MapNoMatch):
        return AdaptationError(
            declaration,
            expression.source,
            "Map cannot determine an output type: "
            "no case matched and no default was provided",
        )

    if isinstance(error, UnresolvedCaptureSemanticError):
        return AdaptationError(
            declaration, expression.source, error.message, unresolved_capture=error
        )

    return AdaptationError(declaration, expression.source, error.message)


def _adapt_schema_expression(
    expression: SchemaTypeExpression,
    aliases: tuple[TypeAliasDeclaration, ...],
    declaration: str,
    environment: SemanticEnvironment,
    never_name: str,
    origins: list[GeneratedElementOrigin[SourceSpan]],
    emitted_parameters: tuple[str, ...],
) -> StubTypeExpression:
    expanded = expand_schema_aliases(
        expression, aliases, declaration=declaration
    ).unwrap()
    source_origins: list[_SchemaOrigin] = []
    value = _resolve_schema_source(expanded, environment, source_origins)
    emitted: list[tuple[StaticType, StubTypeExpression]] = []
    generated = static_type_expression(
        value,
        never_name=never_name,
        type_parameters=emitted_parameters,
        on_emit=lambda value, expression: emitted.append((value, expression)),
    )
    for origin in source_origins:
        scopes = _emitted_targets(origin.scope, emitted)
        reachable = {id(node) for scope in scopes for node in walk_type(scope)}
        local = [(value, node) for value, node in emitted if id(node) in reachable]
        origins.extend(
            GeneratedElementOrigin(origin.span, target)
            for target in _emitted_targets(origin.value, local)
        )

    return generated


@dataclass(frozen=True, slots=True)
class _SchemaOrigin:
    span: SourceSpan
    value: StaticType
    scope: StaticType


def _emitted_targets(
    value: StaticType, emitted: list[tuple[StaticType, StubTypeExpression]]
) -> list[StubTypeExpression]:
    identical = [node for candidate, node in emitted if candidate is value]
    if identical:
        return identical

    equivalent = [node for candidate, node in emitted if candidate == value]
    if equivalent:
        return equivalent

    # Flattening removes a union container; its origin follows its members.
    if isinstance(value, UnionType):
        return [
            node
            for member in value.members
            for node in _emitted_targets(member, emitted)
        ]

    return []


def _resolve_schema_source(
    expression: SourceTypeExpression,
    environment: SemanticEnvironment,
    origins: list[_SchemaOrigin],
) -> StaticType:
    match expression:
        case MarkerTypeExpression(
            marker=MarkerKind.EACH | MarkerKind.COLLECT, arguments=(item,)
        ):
            kind: Literal["Each", "Collect"] = (
                "Each" if expression.marker is MarkerKind.EACH else "Collect"
            )
            return VariadicType(
                kind, _resolve_schema_source(item, environment, origins)
            )
        case SchemaTypeExpression(arguments=arguments):
            if len(arguments) != 1:
                raise SemanticLoweringError("Schema requires one type argument")

            value = _resolve_schema_source(arguments[0], environment, origins)
            # Each boundary gets its own value identity, including bound records.
            independent = (
                UnionType(*value.members)
                if isinstance(value, UnionType)
                else replace(value)
            )
            origins[:] = [
                replace(origin, value=independent, scope=independent)
                if origin.value is value and origin.scope is value
                else origin
                for origin in origins
            ]
            origins.append(_SchemaOrigin(expression.span, independent, independent))
            return independent
        case AppliedTypeExpression(constructor=constructor, arguments=arguments):
            return ParameterizedType(
                _resolve_schema_source(constructor, environment, origins),
                tuple(
                    _resolve_schema_source(argument, environment, origins)
                    for argument in arguments
                ),
            )
        case StarredTypeExpression(item=item):
            return UnpackedType(_resolve_schema_source(item, environment, origins))
        case UnionTypeExpression(members=members):
            start = len(origins)
            value = COMPILER_TYPE_SYSTEM.union(
                tuple(
                    _resolve_schema_source(member, environment, origins)
                    for member in members
                )
            ).unwrap()
            # Restrict deduplication remapping to this union, so an equal plain
            # type elsewhere cannot acquire the discarded boundary's origin.
            origins[start:] = [
                replace(origin, scope=value) for origin in origins[start:]
            ]
            return value
        case _:
            pass

    result = evaluate(
        lower_semantic_expression(expression, environment), COMPILER_TYPE_SYSTEM
    ).unwrap()
    match result:
        case ResolvedType(value=output) | UnresolvedType(value=output):
            return output
        case (
            DeferredMap(possible_output=ResolvedType(value=output))
            | IndeterminateType(possible_output=ResolvedType(value=output))
        ):
            return output
        case _:
            raise ExpectedTypeSemanticError("Schema must evaluate to a type")
