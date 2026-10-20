"""Finite Each/Collect expansion and its variadic fallback."""

from dataclasses import dataclass, replace
from itertools import product

from returns.result import Failure, Result, Success

from typeforge.compiler.specialization._expressions import (
    collect_variable_names,
    fresh_type_parameter_names,
    substitute_scalar,
    type_parameter_name,
    union_types,
)
from typeforge.compiler.specialization._models import (
    ArityFrontier,
    LoweringError,
    LoweringErrorCode,
)
from typeforge.compiler.specialization._predicates import map_specializations
from typeforge.compiler.stub_ir import (
    CaptureType,
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
    is_predicate,
    rewrite_type_children,
    walk_type,
)


def _capture_tokens(expression: StubTypeExpression) -> frozenset[CaptureType]:
    return frozenset(
        item for item in walk_type(expression) if isinstance(item, CaptureType)
    )


def _replace_capture(
    expression: StubTypeExpression,
    bindings: dict[CaptureType, TypeVariable],
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    result = _replace_capture_expression(expression, bindings, on_rewrite)
    if on_rewrite is not None:
        on_rewrite(expression, result)

    return result


def _replace_capture_expression(
    expression: StubTypeExpression,
    bindings: dict[CaptureType, TypeVariable],
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    if isinstance(expression, CaptureType):
        return bindings.get(expression, expression)

    if isinstance(expression, TypeApplication | FixedTuple | UnionExpression):
        return rewrite_type_children(
            expression,
            lambda child: _replace_capture(child, bindings, on_rewrite=on_rewrite),
        )

    return expression


def lower_each_function(
    declaration: FunctionDeclaration,
    frontier: ArityFrontier,
    on_rewrite: TypeRewriteObserver | None = None,
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
    structural_map = _find_collected_map(declaration.return_type, captured_name)
    if structural_map is not None and structural_map.default is None:
        return Failure(
            LoweringError(
                LoweringErrorCode.UNREPRESENTABLE_COVERAGE,
                declaration.name,
                "no-default Each/Collect coverage cannot be published portably; "
                "supply an explicit specialization or fallback",
            )
        )

    if structural_map is not None and any(
        not is_predicate(case.test) and len(_capture_tokens(case.test)) > 1
        for case in structural_map.cases
    ):
        return Failure(
            LoweringError(
                LoweringErrorCode.MULTIPLE_CAPTURES,
                declaration.name,
                "finite callable specialization currently supports one capture "
                "per structural branch",
            )
        )

    signatures = tuple(
        signature
        for arity in range(frontier.minimum, frontier.maximum + 1)
        for signature in _expand_signatures(
            declaration,
            each_parameter,
            each_annotation.item,
            captured_name,
            arity,
            on_rewrite=on_rewrite,
        )
    )
    fallback = _fallback_signature(declaration, on_rewrite=on_rewrite)
    return Success(OverloadDeclaration(signatures, fallback))


@dataclass(frozen=True, slots=True)
class _StructuralMapChoice:
    input_type: StubTypeExpression
    output_type: StubTypeExpression
    is_default: bool


def _expand_signatures(
    declaration: FunctionDeclaration,
    each_parameter: Parameter,
    argument_pattern: StubTypeExpression,
    captured_name: str,
    arity: int,
    on_rewrite: TypeRewriteObserver | None = None,
) -> tuple[FunctionDeclaration, ...]:
    generated_names = fresh_type_parameter_names(
        captured_name, arity, declaration.type_parameters
    )
    generated_types = tuple(TypeVariable(name) for name in generated_names)
    structural_map = _find_collected_map(declaration.return_type, captured_name)
    if structural_map is None:
        return (
            _expand_signature_with_types(
                declaration,
                each_parameter,
                argument_pattern,
                captured_name,
                generated_names,
                generated_types,
                generated_types,
                on_rewrite=on_rewrite,
            ),
        )

    choices = tuple(
        tuple(
            _structural_map_choices(
                structural_map, generated_type, on_rewrite=on_rewrite
            )
        )
        for generated_type in generated_types
    )
    combinations = tuple(product(*choices)) if choices else ((),)
    ordered = sorted(
        combinations,
        key=lambda combination: sum(choice.is_default for choice in combination),
    )
    return tuple(
        _expand_signature_with_types(
            declaration,
            each_parameter,
            argument_pattern,
            captured_name,
            generated_names,
            tuple(choice.input_type for choice in combination),
            tuple(choice.output_type for choice in combination),
            on_rewrite=on_rewrite,
        )
        for combination in ordered
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


def _structural_map_choices(
    mapping: MapType,
    generated_type: TypeVariable,
    on_rewrite: TypeRewriteObserver | None = None,
) -> tuple[_StructuralMapChoice, ...]:
    controller = _map_subject_name(mapping)
    cases: list[_StructuralMapChoice] = []
    for case in map_specializations(mapping, controller):
        if is_predicate(case.test):
            continue

        bindings = {token: generated_type for token in _capture_tokens(case.test)}
        cases.append(
            _StructuralMapChoice(
                _replace_capture(case.test, bindings, on_rewrite=on_rewrite),
                _replace_capture(case.output_type, bindings, on_rewrite=on_rewrite),
                False,
            )
        )

    if mapping.default is None:
        return tuple(cases)

    return (
        *cases,
        _StructuralMapChoice(
            generated_type,
            substitute_scalar(
                mapping.default,
                _map_subject_name(mapping),
                generated_type,
                on_rewrite=on_rewrite,
            ),
            True,
        ),
    )


def _map_subject_name(mapping: MapType) -> str:
    if isinstance(mapping.subject, TypeVariable):
        return mapping.subject.name

    return ""


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

    if isinstance(expression, RuntimeInputType | MapType):
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
