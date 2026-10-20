import ast
from pathlib import Path
from typing import overload

from typeforge.compiler.source._markers import (
    MarkerNormalizationError,
    bind_map_selector,
)
from typeforge.compiler.source._model import (
    AppliedTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceTypeExpression,
    StarredTypeExpression,
    TypeAliasDeclaration,
    TypeParameter,
    TypeParameterKind,
    UnionTypeExpression,
)
from typeforge.compiler.source._syntax import (
    AnnotationSyntaxError,
    ImportBindings,
    expression_name,
    resolve_ast_name,
    resolve_name,
    source_span,
)


def parse_type_alias(
    path: Path,
    source: str,
    node: ast.TypeAlias,
    scope: tuple[str, ...],
    bindings: ImportBindings,
) -> TypeAliasDeclaration:
    value = parse_annotation(path, source, node.value, bindings)
    return TypeAliasDeclaration(
        name=node.name.id,
        qualified_name=(*scope, node.name.id),
        type_parameters=tuple(
            parse_type_parameter(source, parameter)
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec)
        ),
        value=value,
        span=source_span(path, node),
    )


def parse_type_parameter(
    source: str,
    parameter: ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec,
) -> TypeParameter:
    if isinstance(parameter, ast.TypeVar):
        kind = TypeParameterKind.TYPE_VAR
    elif isinstance(parameter, ast.TypeVarTuple):
        kind = TypeParameterKind.TYPE_VAR_TUPLE
    else:
        kind = TypeParameterKind.PARAM_SPEC

    return TypeParameter(
        name=parameter.name,
        kind=kind,
        declaration=ast.get_source_segment(source, parameter) or ast.unparse(parameter),
    )


@overload
def parse_annotation(
    path: Path, source: str, node: ast.expr, bindings: ImportBindings
) -> SourceTypeExpression: ...


@overload
def parse_annotation(
    path: Path, source: str, node: ast.expr | None, bindings: ImportBindings
) -> SourceTypeExpression | None: ...


def parse_annotation(
    path: Path,
    source: str,
    node: ast.expr | None,
    bindings: ImportBindings,
) -> SourceTypeExpression | None:
    if node is None:
        return None

    rendered = ast.get_source_segment(source, node) or ast.unparse(node)
    span = source_span(path, node)
    annotated_value = unwrap_annotated(node, bindings)
    if annotated_value is not None:
        return parse_annotation(path, source, annotated_value, bindings)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        members = tuple(
            parse_annotation(path, source, member, bindings)
            for member in _flatten_union_nodes(node)
        )
        return UnionTypeExpression(rendered, span, members)

    if isinstance(node, ast.Starred):
        item = parse_annotation(path, source, node.value, bindings)
        return StarredTypeExpression(rendered, span, item)

    if isinstance(node, ast.Name | ast.Attribute):
        name = expression_name(node)
        name_expression = NameTypeExpression(
            source=rendered,
            span=span,
            name=name,
            qualified_name=resolve_name(name, bindings),
        )
        if _is_runtime_input(name_expression):
            return RuntimeInputTypeExpression(rendered, span)

        marker = _marker_kind(name_expression)
        if marker is not None:
            return MarkerTypeExpression(
                source=rendered,
                span=span,
                marker=marker,
                arguments=(),
            )

        return name_expression

    if isinstance(node, ast.Subscript):
        constructor = parse_annotation(path, source, node.value, bindings)
        slice_nodes = (
            node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
        )
        marker = _marker_kind(constructor)
        public_map = isinstance(node.value, ast.Name | ast.Attribute) and (
            resolve_name(expression_name(node.value), bindings) == ("typeforge", "Map")
        )
        argument_values: list[SourceTypeExpression] = []
        for slice_node in slice_nodes:
            if public_map:
                if not argument_values and isinstance(slice_node, ast.Slice):
                    raise AnnotationSyntaxError(
                        "Map requires a subject before its branches",
                        source_span(path, slice_node),
                    )

                if (
                    len(argument_values) > 1
                    and _marker_kind(argument_values[-1]) is MarkerKind.DEFAULT
                ):
                    raise AnnotationSyntaxError(
                        "Map fallback must be last; no branch may follow it",
                        source_span(path, slice_node),
                    )

                if argument_values and not isinstance(slice_node, ast.Slice):
                    raise AnnotationSyntaxError(
                        "Map entries must use selector: output or ...: output syntax",
                        source_span(path, slice_node),
                    )

            argument = (
                _parse_map_slice(
                    path,
                    source,
                    slice_node,
                    bindings,
                    argument_values[0],
                )
                if marker is MarkerKind.MAP
                and isinstance(slice_node, ast.Slice)
                and argument_values
                else parse_annotation(path, source, slice_node, bindings)
            )
            argument_values.append(argument)

        arguments = tuple(argument_values)
        if (
            isinstance(node.value, ast.Name | ast.Attribute)
            and resolve_name(expression_name(node.value), bindings)
            == ("typeforge", "Is")
            and len(arguments) != 1
        ):
            raise AnnotationSyntaxError("Is requires one type argument", span)

        if _is_schema_boundary(constructor):
            return SchemaTypeExpression(
                source=rendered,
                span=span,
                arguments=arguments,
            )

        if marker is not None:
            return MarkerTypeExpression(
                source=rendered,
                span=span,
                marker=marker,
                arguments=arguments,
            )

        return AppliedTypeExpression(
            source=rendered,
            span=span,
            constructor=constructor,
            arguments=arguments,
        )

    return RawTypeExpression(source=rendered, span=span)


def _parse_map_slice(
    path: Path,
    source: str,
    node: ast.Slice,
    bindings: ImportBindings,
    subject: SourceTypeExpression,
) -> MarkerTypeExpression:
    """Normalize branch spelling without changing matching or output semantics."""
    rendered = ast.get_source_segment(source, node) or ast.unparse(node)
    span = source_span(path, node)
    if node.step is not None and not (
        isinstance(node.step, ast.Constant) and node.step.value is None
    ):
        raise AnnotationSyntaxError(
            "Map branches do not accept a slice step", source_span(path, node.step)
        )

    output = parse_annotation(path, source, node.upper, bindings)
    # A missing token denotes None. Anchor synthesized endpoints to the branch
    # that supplied them, while retaining its exact authored spelling above.
    if output is None:
        output = RawTypeExpression("None", span)

    if isinstance(node.lower, ast.Constant) and node.lower.value is Ellipsis:
        return MarkerTypeExpression(rendered, span, MarkerKind.DEFAULT, (output,))

    selector = parse_annotation(
        path, source, node.lower, bindings
    ) or RawTypeExpression("None", span)

    try:
        bound_selector = bind_map_selector(selector, subject)
    except MarkerNormalizationError as error:
        raise AnnotationSyntaxError(
            error.message, error.span or selector.span
        ) from error

    return MarkerTypeExpression(
        rendered,
        span,
        MarkerKind.CASE,
        (bound_selector, output),
    )


def unwrap_annotated(node: ast.expr, bindings: ImportBindings) -> ast.expr | None:
    if not isinstance(node, ast.Subscript):
        return None

    if resolve_ast_name(node.value, bindings) not in {
        ("typing", "Annotated"),
        ("typing_extensions", "Annotated"),
    }:
        return None

    arguments = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
    if len(arguments) < 2:
        return None

    return arguments[0]


def _flatten_union_nodes(node: ast.expr) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return (*_flatten_union_nodes(node.left), *_flatten_union_nodes(node.right))

    return (node,)


def _marker_kind(expression: SourceTypeExpression) -> MarkerKind | None:
    if isinstance(expression, MarkerTypeExpression):
        return expression.marker

    if not isinstance(expression, NameTypeExpression):
        return None

    qualified_name = expression.qualified_name
    marker_names = {marker.value: marker for marker in MarkerKind}
    if qualified_name is None or len(qualified_name) < 2:
        return None

    if qualified_name[:-1] not in {
        ("typeforge",),
        ("typeforge", "_markers"),
    }:
        return None

    if qualified_name[:-1] == ("typeforge",) and qualified_name[-1] in {
        "Case",
        "Default",
    }:
        return None

    if qualified_name == ("typeforge", "Is"):
        return MarkerKind.EQUAL

    if qualified_name[:-1] == ("typeforge",) and qualified_name[-1] in {
        "Equal",
        "Assignable",
        "All",
        "Any",
        "Not",
    }:
        raise AnnotationSyntaxError(
            f"{qualified_name[-1]} is no longer a public selector; "
            "use a bare type or Is[Type]",
            expression.span,
        )

    return marker_names.get(qualified_name[-1])


def _is_schema_boundary(expression: SourceTypeExpression) -> bool:
    return isinstance(expression, NameTypeExpression) and expression.qualified_name == (
        "typeforge",
        "pydantic",
        "Schema",
    )


def _is_runtime_input(expression: SourceTypeExpression) -> bool:
    return isinstance(expression, NameTypeExpression) and expression.qualified_name == (
        "typeforge",
        "pydantic",
        "Input",
    )
