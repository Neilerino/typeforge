import ast
from dataclasses import replace
from pathlib import Path
from typing import overload

from typeforge.compiler.source._markers import (
    MarkerNormalizationError,
    bind_map_selector,
)
from typeforge.compiler.source._model import (
    AppliedTypeExpression,
    FieldConstructionTypeExpression,
    FieldReferenceTypeExpression,
    FieldReplacementTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RecordTypeExpression,
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
            parse_type_parameter(path, source, parameter, bindings)
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec)
        ),
        value=value,
        span=source_span(path, node),
    )


def parse_type_parameter(
    path: Path,
    source: str,
    parameter: ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec,
    bindings: ImportBindings,
) -> TypeParameter:
    if isinstance(parameter, ast.TypeVar):
        kind = TypeParameterKind.TYPE_VAR
    elif isinstance(parameter, ast.TypeVarTuple):
        kind = TypeParameterKind.TYPE_VAR_TUPLE
    else:
        kind = TypeParameterKind.PARAM_SPEC

    domain: SourceTypeExpression | None = None
    if isinstance(parameter, ast.TypeVar) and parameter.bound is not None:
        if isinstance(parameter.bound, ast.Tuple):
            members = tuple(
                parse_annotation(path, source, item, bindings)
                for item in parameter.bound.elts
            )
            domain = UnionTypeExpression(
                source=ast.unparse(parameter.bound),
                span=source_span(path, parameter.bound),
                members=members,
            )
        else:
            domain = parse_annotation(path, source, parameter.bound, bindings)

    return TypeParameter(
        name=parameter.name,
        kind=kind,
        declaration=ast.get_source_segment(source, parameter) or ast.unparse(parameter),
        domain=domain,
        span=source_span(path, parameter),
        has_default=parameter.default_value is not None,
    )


def validate_construction_expression(
    path: Path, node: ast.AST, bindings: ImportBindings
) -> None:
    if isinstance(node, ast.expr):
        annotated = unwrap_annotated(node, bindings)
        if annotated is not None:
            validate_construction_expression(path, annotated, bindings)
            return

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name | ast.Attribute) and resolve_ast_name(
            node.func, bindings
        ) == ("typeforge", "Field"):
            for keyword in node.keywords:
                validate_construction_expression(path, keyword.value, bindings)

            return

        if _is_field_replacement(node, bindings):
            assert isinstance(node.func, ast.Attribute)
            validate_construction_expression(path, node.func.value, bindings)
            for keyword in node.keywords:
                validate_construction_expression(path, keyword.value, bindings)

            return

        generator = _record_generator(path, node, bindings)
        # The element is validated by _parse_record after its lexical field
        # binding exists; the operand still belongs to the enclosing scope.
        validate_construction_expression(path, generator.generators[0].iter, bindings)
        return

    if isinstance(
        node,
        ast.Lambda
        | ast.ListComp
        | ast.SetComp
        | ast.DictComp
        | ast.GeneratorExp
        | ast.NamedExpr
        | ast.IfExp
        | ast.BoolOp
        | ast.Compare,
    ) or (isinstance(node, ast.BinOp) and not isinstance(node.op, ast.BitOr)):
        raise AnnotationSyntaxError(
            "unsupported type_function construction expression", source_span(path, node)
        )

    for child in ast.iter_child_nodes(node):
        validate_construction_expression(path, child, bindings)


def _record_generator(
    path: Path, node: ast.Call, bindings: ImportBindings
) -> ast.GeneratorExp:
    if not (
        isinstance(node.func, ast.Name | ast.Attribute)
        and resolve_ast_name(node.func, bindings) == ("typeforge", "Record")
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.GeneratorExp)
    ):
        raise AnnotationSyntaxError(
            "unsupported type_function construction; Record requires a Fields "
            "generator",
            source_span(path, node),
        )

    generator = node.args[0]
    if len(generator.generators) != 1:
        raise AnnotationSyntaxError(
            "Record currently requires one Fields iteration",
            source_span(path, generator),
        )

    iteration = generator.generators[0]
    if not (
        isinstance(iteration.target, ast.Name)
        and not iteration.ifs
        and not iteration.is_async
        and isinstance(iteration.iter, ast.Subscript)
        and isinstance(iteration.iter.value, ast.Name | ast.Attribute)
        and resolve_ast_name(iteration.iter.value, bindings) == ("typeforge", "Fields")
        and not isinstance(iteration.iter.slice, ast.Tuple)
    ):
        raise AnnotationSyntaxError(
            "Record requires one named binding over Fields[T], without filters",
            source_span(path, generator),
        )

    return generator


def _is_field_replacement(node: ast.Call, bindings: ImportBindings) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "replace":
        return False

    target = node.func.value
    if isinstance(target, ast.Name):
        return target.id in dict(bindings.fields)

    if isinstance(target, ast.Call):
        return (
            isinstance(target.func, ast.Name | ast.Attribute)
            and resolve_ast_name(target.func, bindings) == ("typeforge", "Field")
        ) or _is_field_replacement(target, bindings)

    return False


def _field_keywords(
    path: Path, node: ast.Call, *, constructing: bool
) -> dict[str, ast.expr]:
    message = "Field requires keyword data: name, type, required, and readonly"
    if node.args:
        raise AnnotationSyntaxError(message, source_span(path, node))

    keywords: dict[str, ast.expr] = {}
    for keyword in node.keywords:
        if (
            keyword.arg is None
            or keyword.arg not in {"name", "type", "required", "readonly"}
            or keyword.arg in keywords
        ):
            raise AnnotationSyntaxError(message, source_span(path, keyword))

        keywords[keyword.arg] = keyword.value

    if constructing and not {"name", "type"}.issubset(keywords):
        raise AnnotationSyntaxError(
            "Field requires name and type keywords", source_span(path, node)
        )

    return keywords


def _parse_field_replacement(
    path: Path, source: str, node: ast.Call, bindings: ImportBindings
) -> FieldReplacementTypeExpression:
    assert isinstance(node.func, ast.Attribute)
    keywords = _field_keywords(path, node, constructing=False)
    field = parse_annotation(path, source, node.func.value, bindings)
    return FieldReplacementTypeExpression(
        ast.get_source_segment(source, node) or ast.unparse(node),
        source_span(path, node),
        field,
        name=parse_annotation(path, source, keywords.get("name"), bindings),
        value=parse_annotation(path, source, keywords.get("type"), bindings),
        required=_field_modifier(path, keywords["required"])
        if "required" in keywords
        else None,
        readonly=_field_modifier(path, keywords["readonly"])
        if "readonly" in keywords
        else None,
    )


def _parse_field(
    path: Path, source: str, node: ast.Call, bindings: ImportBindings
) -> FieldConstructionTypeExpression:
    keywords = _field_keywords(path, node, constructing=True)
    name = parse_annotation(path, source, keywords["name"], bindings)
    value = parse_annotation(path, source, keywords["type"], bindings)
    return FieldConstructionTypeExpression(
        ast.get_source_segment(source, node) or ast.unparse(node),
        source_span(path, node),
        name,
        value,
        required=_field_modifier(path, keywords["required"])
        if "required" in keywords
        else True,
        readonly=_field_modifier(path, keywords["readonly"])
        if "readonly" in keywords
        else False,
    )


def _field_modifier(path: Path, node: ast.expr) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value

    raise AnnotationSyntaxError(
        "field modifiers must be booleans", source_span(path, node)
    )


def _parse_record(
    path: Path, source: str, node: ast.Call, bindings: ImportBindings
) -> RecordTypeExpression:
    generator = _record_generator(path, node, bindings)
    iteration = generator.generators[0]
    assert isinstance(iteration.target, ast.Name)
    assert isinstance(iteration.iter, ast.Subscript)
    record = parse_annotation(path, source, iteration.iter.slice, bindings)
    name = iteration.target.id
    declaration = source_span(path, iteration.target)
    binding = FieldReferenceTypeExpression(name, declaration, name, declaration)
    local = replace(
        bindings,
        fields=(*bindings.fields, (name, binding)),
        names=tuple(item for item in bindings.names if item[0] != name),
        captures=tuple(item for item in bindings.captures if item[0] != name),
    )
    validate_construction_expression(path, generator.elt, local)
    transform = parse_annotation(path, source, generator.elt, local)
    return RecordTypeExpression(
        ast.get_source_segment(source, node) or ast.unparse(node),
        source_span(path, node),
        record,
        binding,
        transform,
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
        field_name = (
            node.id
            if isinstance(node, ast.Name)
            else (node.value.id if isinstance(node.value, ast.Name) else None)
        )
        field = (
            dict(bindings.fields).get(field_name) if field_name is not None else None
        )
        if field is not None:
            attribute = node.attr if isinstance(node, ast.Attribute) else None
            if attribute not in (None, "name", "type"):
                raise AnnotationSyntaxError(
                    "unsupported symbolic field attribute", span
                )

            return replace(field, source=rendered, span=span, attribute=attribute)

        if (
            isinstance(node, ast.Name)
            and (capture := dict(bindings.captures).get(node.id)) is not None
        ):
            return replace(capture, source=rendered, span=span)

        name = expression_name(node)
        name_expression = NameTypeExpression(
            source=rendered,
            span=span,
            name=name,
            qualified_name=resolve_name(name, bindings),
        )
        if name_expression.qualified_name in {
            ("typeforge", "MapFields"),
            ("typeforge", "Key"),
            ("typeforge", "Value"),
        }:
            raise AnnotationSyntaxError(
                "field authoring requires Record and Fields", span
            )

        if name_expression.qualified_name in {
            ("typeforge", "OptionalField"),
            ("typeforge", "ReadonlyField"),
        }:
            raise AnnotationSyntaxError(
                "field authoring requires keyword Field construction", span
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

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name | ast.Attribute) and resolve_ast_name(
            node.func, bindings
        ) == ("typeforge", "Field"):
            return _parse_field(path, source, node, bindings)

        if _is_field_replacement(node, bindings):
            return _parse_field_replacement(path, source, node, bindings)

        return _parse_record(path, source, node, bindings)

    if isinstance(node, ast.Subscript):
        if resolve_ast_name(node.value, bindings) == ("typeforge", "Field"):
            raise AnnotationSyntaxError("Field requires keyword construction", span)

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
