"""Finite Each/Collect expansion and its variadic fallback."""

from dataclasses import replace
from itertools import product

from returns.result import Failure, Result, Success

from typeforge.compiler.semantic_adapter import SemanticEnvironment
from typeforge.compiler.specialization._bounds import checker_type_bound
from typeforge.compiler.specialization._expressions import (
    collect_variable_names,
    fresh_type_parameter_names,
    substitute_scalar,
    type_parameter_name,
    union_types,
)
from typeforge.compiler.specialization._map_lowering import lower_map_function
from typeforge.compiler.specialization._models import (
    ArityFrontier,
    LoweringError,
    LoweringErrorCode,
)
from typeforge.compiler.stub_ir import (
    CollectType,
    EachType,
    FixedTuple,
    FunctionDeclaration,
    HomogeneousTuple,
    MapType,
    OverloadDeclaration,
    Parameter,
    ParameterKind,
    RuntimeInputType,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeRewriteObserver,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    rewrite_type,
    rewrite_type_children,
    substitute_type,
    walk_declaration,
)
from typeforge.utils.error_handling import safe_result


def lower_each_function(
    declaration: FunctionDeclaration,
    frontier: ArityFrontier,
    on_rewrite: TypeRewriteObserver | None = None,
    *,
    environment: SemanticEnvironment = (),
    reserved_type_parameters: tuple[str, ...] = (),
) -> Result[FunctionDeclaration | OverloadDeclaration, LoweringError]:
    each_parameters = tuple(
        (parameter, parameter.annotation)
        for parameter in declaration.parameters
        if isinstance(parameter.annotation, EachType)
    )
    if not each_parameters:
        return Success(declaration)

    if len(each_parameters) != 1:
        return Failure(
            LoweringError(
                LoweringErrorCode.MULTIPLE_CAPTURES,
                declaration.name,
                "a function must contain exactly one Each parameter",
            )
        )

    each_parameter, each_annotation = each_parameters[0]

    if each_parameter.kind is not ParameterKind.VAR_POSITIONAL:
        return Failure(
            LoweringError(
                LoweringErrorCode.INVALID_EACH_POSITION,
                declaration.name,
                "Each must annotate a variadic positional parameter",
            )
        )

    captured_names = collect_variable_names(each_annotation.item)
    if len(captured_names) != 1:
        return Failure(
            LoweringError(
                LoweringErrorCode.MISSING_CAPTURE,
                declaration.name,
                "Each must contain exactly one type variable",
            )
        )

    captured_name = captured_names[0]
    return _specialize_each(
        declaration,
        frontier,
        each_parameter,
        each_annotation.item,
        captured_name,
        environment,
        reserved_type_parameters,
        on_rewrite,
    )


@safe_result(errors=(LoweringError,))
def _specialize_each(
    declaration: FunctionDeclaration,
    frontier: ArityFrontier,
    each_parameter: Parameter,
    argument_pattern: StubTypeExpression,
    captured_name: str,
    environment: SemanticEnvironment,
    reserved_type_parameters: tuple[str, ...],
    on_rewrite: TypeRewriteObserver | None,
) -> OverloadDeclaration:
    signatures = tuple(
        signature
        for arity in range(frontier.minimum, frontier.maximum + 1)
        for signature in _expand_signatures(
            declaration,
            each_parameter,
            argument_pattern,
            captured_name,
            arity,
            environment=environment,
            reserved_type_parameters=reserved_type_parameters,
            on_rewrite=on_rewrite,
        )
    )
    mapping = _find_collected_map(declaration.return_type, captured_name)
    if mapping is not None:
        scalar = _each_map_projection(
            declaration,
            mapping,
            TypeVariable(captured_name),
            environment,
            reserved_type_parameters,
            on_rewrite,
        ).unwrap()
        aggregate = (
            scalar.fallback if isinstance(scalar, OverloadDeclaration) else scalar
        )
        domain = aggregate.parameters[0].annotation
        output = checker_type_bound(
            aggregate.return_type,
            type_parameters=frozenset(
                type_parameter_name(name) for name in declaration.type_parameters
            ),
        )
        declaration = replace(
            declaration,
            parameters=tuple(
                replace(
                    parameter,
                    annotation=substitute_type(
                        parameter.annotation,
                        captured_name,
                        domain,
                        on_rewrite=on_rewrite,
                    ),
                )
                for parameter in declaration.parameters
            ),
            return_type=rewrite_type(
                declaration.return_type,
                lambda item: output if item == mapping else None,
                on_rewrite=on_rewrite,
            ),
            type_parameters=aggregate.type_parameters,
            type_parameter_domains=aggregate.type_parameter_domains,
            type_parameter_defaults=aggregate.type_parameter_defaults,
        )

    fallback = _fallback_signature(declaration, on_rewrite=on_rewrite)
    return OverloadDeclaration(signatures, fallback)


def _expand_signatures(
    declaration: FunctionDeclaration,
    each_parameter: Parameter,
    argument_pattern: StubTypeExpression,
    captured_name: str,
    arity: int,
    on_rewrite: TypeRewriteObserver | None = None,
    *,
    environment: SemanticEnvironment = (),
    reserved_type_parameters: tuple[str, ...] = (),
) -> tuple[FunctionDeclaration, ...]:
    reserved = (
        *declaration.type_parameters,
        *reserved_type_parameters,
        *(
            item.name
            for item in walk_declaration(declaration)
            if isinstance(item, TypeName | TypeVariable)
        ),
    )
    generated_names = fresh_type_parameter_names(captured_name, arity, reserved)
    generated_types = tuple(TypeVariable(name) for name in generated_names)
    structural_map = _find_collected_map(declaration.return_type, captured_name)
    if structural_map is None:
        bound = dict(declaration.type_parameter_domains).get(captured_name)
        return (
            _expand_signature_with_types(
                declaration,
                each_parameter,
                argument_pattern,
                captured_name,
                tuple(
                    _position_type_parameter(declaration, captured_name, name)
                    for name in generated_names
                ),
                generated_types,
                generated_types,
                generated_domains=(
                    tuple((name, bound) for name in generated_names)
                    if bound is not None
                    else ()
                ),
                on_rewrite=on_rewrite,
            ),
        )

    choices: list[tuple[FunctionDeclaration, ...]] = []
    aggregates: list[FunctionDeclaration] = []
    reserved += generated_names
    for generated_type in generated_types:
        scalar = _each_map_projection(
            declaration,
            structural_map,
            generated_type,
            environment,
            reserved,
            on_rewrite,
        ).unwrap()
        if isinstance(scalar, OverloadDeclaration):
            choices.append(scalar.signatures)
            aggregates.append(scalar.fallback)
            position = (*scalar.signatures, scalar.fallback)
        else:
            choices.append((scalar,))
            position = (scalar,)

        reserved += tuple(
            name for signature in position for name in signature.type_parameters
        )

    # Mixed generic fallbacks overlap with incompatible tuple returns. Generate
    # only closed combinations, followed by the complete aggregate when present.
    combinations = tuple(product(*choices))
    if aggregates and len(aggregates) == len(choices):
        combinations += (tuple(aggregates),)

    return tuple(
        _expand_mapped_signature(
            declaration,
            each_parameter,
            argument_pattern,
            captured_name,
            combination,
            on_rewrite,
        )
        for combination in combinations
    )


def _expand_mapped_signature(
    declaration: FunctionDeclaration,
    each_parameter: Parameter,
    argument_pattern: StubTypeExpression,
    captured_name: str,
    combination: tuple[FunctionDeclaration, ...],
    on_rewrite: TypeRewriteObserver | None,
) -> FunctionDeclaration:
    retained_names = {
        type_parameter_name(original)
        for original in declaration.type_parameters
        if type_parameter_name(original) != captured_name
    }
    parameters = tuple(
        dict.fromkeys(
            name
            for choice in combination
            for name in choice.type_parameters
            if type_parameter_name(name) not in retained_names
        )
    )
    domains = tuple(
        dict.fromkeys(
            domain
            for choice in combination
            for domain in choice.type_parameter_domains
            if domain[0] not in retained_names
        )
    )
    return _expand_signature_with_types(
        declaration,
        each_parameter,
        argument_pattern,
        captured_name,
        parameters,
        tuple(choice.parameters[0].annotation for choice in combination),
        tuple(choice.return_type for choice in combination),
        generated_domains=domains,
        on_rewrite=on_rewrite,
    )


def _expand_signature_with_types(
    declaration: FunctionDeclaration,
    each_parameter: Parameter,
    argument_pattern: StubTypeExpression,
    captured_name: str,
    generated_names: tuple[str, ...],
    captured_inputs: tuple[StubTypeExpression, ...],
    collected_outputs: tuple[StubTypeExpression, ...],
    on_rewrite: TypeRewriteObserver | None = None,
    *,
    generated_domains: tuple[tuple[str, StubTypeExpression], ...] = (),
) -> FunctionDeclaration:
    expanded_parameters: list[Parameter] = []
    for parameter in declaration.parameters:
        if parameter is not each_parameter:
            expanded_parameters.append(parameter)
            continue

        positional_kind = _expanded_parameter_kind(tuple(expanded_parameters))
        for index, item in enumerate(captured_inputs, start=1):
            annotation = substitute_scalar(
                argument_pattern, captured_name, item, on_rewrite=on_rewrite
            )
            if on_rewrite is not None:
                on_rewrite(each_parameter.annotation, annotation)

            expanded_parameters.append(
                Parameter(f"{each_parameter.name}_{index}", annotation, positional_kind)
            )

    retained = tuple(
        parameter
        for parameter in declaration.type_parameters
        if type_parameter_name(parameter) != captured_name
    )
    return replace(
        declaration,
        parameters=tuple(expanded_parameters),
        return_type=_substitute_collect(
            declaration.return_type,
            captured_name,
            collected_outputs,
            on_rewrite=on_rewrite,
        ),
        type_parameters=retained + generated_names,
        type_parameter_domains=(
            *(
                (name, bound)
                for name, bound in declaration.type_parameter_domains
                if name != captured_name
            ),
            *generated_domains,
        ),
        type_parameter_defaults=tuple(
            name
            for name in declaration.type_parameter_defaults
            if name != captured_name
        ),
    )


def _find_collected_map(
    expression: StubTypeExpression, captured_name: str
) -> MapType | None:
    if (
        isinstance(expression, CollectType)
        and isinstance(expression.item, MapType)
        and expression.item.subject == TypeVariable(captured_name)
    ):
        return expression.item

    if isinstance(expression, TypeApplication):
        for argument in expression.arguments:
            found = _find_collected_map(argument, captured_name)
            if found is not None:
                return found

    if isinstance(expression, FixedTuple | UnionExpression):
        items = (
            expression.items
            if isinstance(expression, FixedTuple)
            else expression.members
        )
        for item in items:
            found = _find_collected_map(item, captured_name)
            if found is not None:
                return found

    if isinstance(expression, UnpackedType):
        return _find_collected_map(expression.item, captured_name)

    return None


def _each_map_projection(
    declaration: FunctionDeclaration,
    mapping: MapType,
    generated_type: TypeVariable,
    environment: SemanticEnvironment,
    reserved: tuple[str, ...],
    on_rewrite: TypeRewriteObserver | None,
) -> Result[FunctionDeclaration | OverloadDeclaration, LoweringError]:
    assert isinstance(mapping.subject, TypeVariable)
    controller = mapping.subject.name
    projected = substitute_type(mapping, controller, generated_type)
    assert isinstance(projected, MapType)
    scalar = replace(
        declaration,
        parameters=(Parameter("value", generated_type),),
        return_type=projected,
        type_parameters=(
            *(
                name
                for name in declaration.type_parameters
                if type_parameter_name(name) != controller
            ),
            _position_type_parameter(declaration, controller, generated_type.name),
        ),
        type_parameter_domains=tuple(
            (generated_type.name if name == controller else name, bound)
            for name, bound in declaration.type_parameter_domains
        ),
        type_parameter_defaults=tuple(
            generated_type.name if name == controller else name
            for name in declaration.type_parameter_defaults
        ),
    )
    return lower_map_function(
        scalar,
        projected,
        on_rewrite=on_rewrite,
        environment=environment,
        reserved_type_parameters=reserved,
    )


def _fallback_signature(
    declaration: FunctionDeclaration, on_rewrite: TypeRewriteObserver | None = None
) -> FunctionDeclaration:
    type_var_tuples = frozenset(
        type_parameter_name(parameter)
        for parameter in declaration.type_parameters
        if parameter.lstrip().startswith("*")
    )
    transformed_type_var_tuples = frozenset(
        name
        for parameter in declaration.parameters
        if isinstance(parameter.annotation, EachType)
        and not isinstance(parameter.annotation.item, TypeVariable)
        for name in collect_variable_names(parameter.annotation.item)
        if name in type_var_tuples
    )
    return replace(
        declaration,
        parameters=tuple(
            replace(
                parameter,
                annotation=_erase_markers(
                    parameter.annotation,
                    type_var_tuples,
                    transformed_type_var_tuples,
                    on_rewrite=on_rewrite,
                ),
            )
            for parameter in declaration.parameters
        ),
        return_type=_erase_markers(
            declaration.return_type,
            type_var_tuples,
            transformed_type_var_tuples,
            on_rewrite=on_rewrite,
        ),
        type_parameters=tuple(
            parameter
            for parameter in declaration.type_parameters
            if type_parameter_name(parameter) not in transformed_type_var_tuples
        ),
    )


def _expanded_parameter_kind(
    preceding: tuple[Parameter, ...],
) -> ParameterKind:
    if all(parameter.kind is ParameterKind.POSITIONAL_ONLY for parameter in preceding):
        return ParameterKind.POSITIONAL_ONLY

    return ParameterKind.POSITIONAL_OR_KEYWORD


def _position_type_parameter(
    declaration: FunctionDeclaration, controller: str, generated_name: str
) -> str:
    original = next(
        (
            parameter.lstrip()
            for parameter in declaration.type_parameters
            if type_parameter_name(parameter) == controller
            and not parameter.lstrip().startswith("*")
        ),
        controller,
    )
    return generated_name + original[len(controller) :]


def _substitute_collect(
    expression: StubTypeExpression,
    variable: str,
    replacements: tuple[StubTypeExpression, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    result = _substitute_collect_expression(
        expression, variable, replacements, on_rewrite
    )
    if on_rewrite is not None:
        on_rewrite(expression, result)

    return result


def _substitute_collect_expression(
    expression: StubTypeExpression,
    variable: str,
    replacements: tuple[StubTypeExpression, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    if isinstance(expression, CollectType):
        if _collects_variable(expression.item, variable):
            if on_rewrite is not None:
                for replacement in replacements:
                    on_rewrite(expression.item, replacement)

            return FixedTuple(replacements)

        return expression

    if isinstance(expression, TypeApplication):
        arguments: list[StubTypeExpression] = []
        for argument in expression.arguments:
            if (
                isinstance(argument, UnpackedType)
                and isinstance(argument.item, CollectType)
                and _collects_variable(argument.item.item, variable)
            ):
                if on_rewrite is not None:
                    for replacement in replacements:
                        on_rewrite(argument, replacement)
                        on_rewrite(argument.item, replacement)
                        on_rewrite(argument.item.item, replacement)

                arguments.extend(replacements)
            else:
                arguments.append(
                    _substitute_collect(
                        argument, variable, replacements, on_rewrite=on_rewrite
                    )
                )

        return TypeApplication(
            _substitute_collect(
                expression.constructor, variable, replacements, on_rewrite=on_rewrite
            ),
            tuple(arguments),
        )

    if isinstance(expression, FixedTuple | UnpackedType | UnionExpression):
        return rewrite_type_children(
            expression,
            lambda child: _substitute_collect(
                child, variable, replacements, on_rewrite=on_rewrite
            ),
        )

    return expression


def _collects_variable(expression: StubTypeExpression, variable: str) -> bool:
    return expression == TypeVariable(variable) or (
        isinstance(expression, MapType) and expression.subject == TypeVariable(variable)
    )


def _erase_markers(
    expression: StubTypeExpression,
    type_var_tuples: frozenset[str] = frozenset(),
    broad_type_var_tuples: frozenset[str] = frozenset(),
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    result = _erase_markers_expression(
        expression, type_var_tuples, broad_type_var_tuples, on_rewrite
    )
    if on_rewrite is not None:
        on_rewrite(expression, result)

    return result


def _erase_markers_expression(
    expression: StubTypeExpression,
    type_var_tuples: frozenset[str] = frozenset(),
    broad_type_var_tuples: frozenset[str] = frozenset(),
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    if isinstance(expression, EachType):
        item = _erase_markers(
            expression.item,
            type_var_tuples,
            broad_type_var_tuples,
            on_rewrite=on_rewrite,
        )
        for name in broad_type_var_tuples:
            item = substitute_scalar(
                item, name, TypeName("object"), on_rewrite=on_rewrite
            )

        if isinstance(item, TypeVariable) and item.name in type_var_tuples:
            return UnpackedType(item)

        return item

    if isinstance(expression, CollectType):
        item = _erase_markers(
            expression.item,
            type_var_tuples,
            broad_type_var_tuples,
            on_rewrite=on_rewrite,
        )
        if isinstance(item, TypeVariable) and item.name in broad_type_var_tuples:
            erased = TypeName("object")
            if on_rewrite is not None:
                on_rewrite(item, erased)

            return HomogeneousTuple(erased)

        if isinstance(item, TypeVariable) and item.name in type_var_tuples:
            return FixedTuple((UnpackedType(item),))

        return HomogeneousTuple(item)

    if isinstance(expression, MapType):
        return checker_type_bound(expression, on_rewrite=on_rewrite)

    if isinstance(expression, RuntimeInputType):
        return TypeName("object")

    if isinstance(expression, TypeApplication | FixedTuple | HomogeneousTuple):
        return rewrite_type_children(
            expression,
            lambda child: _erase_markers(
                child, type_var_tuples, broad_type_var_tuples, on_rewrite=on_rewrite
            ),
        )

    if isinstance(expression, UnpackedType):
        if isinstance(expression.item, CollectType):
            collected_item = _erase_markers(
                expression.item.item,
                type_var_tuples,
                broad_type_var_tuples,
                on_rewrite=on_rewrite,
            )
            if (
                isinstance(collected_item, TypeVariable)
                and collected_item.name in broad_type_var_tuples
            ):
                erased = TypeName("object")
                broad = HomogeneousTuple(erased)
                if on_rewrite is not None:
                    on_rewrite(collected_item, erased)
                    on_rewrite(expression.item, broad)

                return UnpackedType(broad)

            if (
                isinstance(collected_item, TypeVariable)
                and collected_item.name in type_var_tuples
            ):
                if on_rewrite is not None:
                    on_rewrite(expression.item, collected_item)

                return UnpackedType(collected_item)

        return UnpackedType(
            _erase_markers(
                expression.item,
                type_var_tuples,
                broad_type_var_tuples,
                on_rewrite=on_rewrite,
            )
        )

    if isinstance(expression, UnionExpression):
        return union_types(
            tuple(
                _erase_markers(
                    member,
                    type_var_tuples,
                    broad_type_var_tuples,
                    on_rewrite=on_rewrite,
                )
                for member in expression.members
            ),
            on_rewrite=on_rewrite,
        )

    return expression
