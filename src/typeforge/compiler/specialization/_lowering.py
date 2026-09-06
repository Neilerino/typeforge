from dataclasses import dataclass, replace
from itertools import product

from returns.result import Failure, Result, Success

from typeforge.compiler.specialization._models import (
    ArityFrontier,
    LoweringError,
    LoweringErrorCode,
)
from typeforge.compiler.stub_ir import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    ClassDeclaration,
    CollectType,
    Declaration,
    EachType,
    EqualPredicate,
    FixedTuple,
    FunctionDeclaration,
    GeneratedElementOrigin,
    HomogeneousTuple,
    Import,
    ImportFrom,
    LiteralType,
    MapCase,
    MapType,
    MapValueType,
    ModuleImport,
    NotPredicate,
    OverloadDeclaration,
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
    TypeRewriteObserver,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    VariableDeclaration,
    is_predicate,
    merge_imports,
    rewrite_type_children,
    walk_module,
    walk_type,
)


def lower_variadic_module(
    module: StubModule, frontier: ArityFrontier
) -> Result[StubModule, LoweringError]:
    if frontier.minimum < 0 or frontier.maximum < frontier.minimum:
        return Failure(
            LoweringError(
                LoweringErrorCode.INVALID_FRONTIER,
                module.name,
                "arity frontier must satisfy 0 <= minimum <= maximum",
            )
        )

    lowered: list[Declaration] = []
    origins = module.origins
    expression_origins = list(module.origins)

    def record_rewrite(
        original: StubTypeExpression, replacement: StubTypeExpression
    ) -> None:
        if original is not replacement:
            expression_origins.extend(
                replace(item, generated=replacement)
                for item in tuple(expression_origins)
                if item.generated is original
            )

    has_overloads = False
    for declaration in module.declarations:
        if isinstance(declaration, ClassDeclaration):
            class_result = _lower_class(
                declaration, frontier, on_rewrite=record_rewrite
            )
            if isinstance(class_result, Failure):
                return class_result

            lowered_class, class_has_overloads = class_result.unwrap()
            has_overloads = has_overloads or class_has_overloads
            lowered.append(lowered_class)
            origins = _replace_declaration_origins(
                origins=origins,
                original=declaration,
                replacement=lowered_class,
            )
            continue

        if not isinstance(declaration, FunctionDeclaration):
            lowered.append(declaration)
            continue

        result = _lower_function(declaration, frontier, on_rewrite=record_rewrite)
        if isinstance(result, Failure):
            return result

        lowered_declaration = result.unwrap()
        has_overloads = has_overloads or isinstance(
            lowered_declaration, OverloadDeclaration
        )
        lowered.append(lowered_declaration)
        origins = _replace_declaration_origins(
            origins,
            declaration,
            lowered_declaration,
        )

    imports = module.imports
    if has_overloads:
        imports = _add_import(imports, ImportFrom("typing", ("overload",)))

    lowered_module = replace(module, declarations=tuple(lowered), imports=imports)
    order: dict[int, int] = {}
    for element in walk_module(lowered_module):
        order.setdefault(id(element), len(order))

    current_origins = {
        (item.origin, id(item.generated)): item
        for item in (*origins, *expression_origins)
        if id(item.generated) in order
    }
    origins = tuple(
        sorted(
            current_origins.values(),
            key=lambda item: (item.origin.start, order[id(item.generated)]),
        )
    )
    lowered_module = replace(lowered_module, origins=origins)
    if _module_contains_literal(lowered_module):
        lowered_module = replace(
            lowered_module,
            imports=_add_import(
                lowered_module.imports, ImportFrom("typing", ("Literal",))
            ),
        )

    return Success(lowered_module)


def _replace_declaration_origins[OriginType](
    origins: tuple[GeneratedElementOrigin[OriginType], ...],
    original: Declaration,
    replacement: Declaration,
) -> tuple[GeneratedElementOrigin[OriginType], ...]:
    if isinstance(original, ClassDeclaration) and isinstance(
        replacement, ClassDeclaration
    ):
        for original_method, replacement_method in zip(
            original.methods, replacement.methods, strict=True
        ):
            origins = _replace_declaration_origins(
                origins, original_method, replacement_method
            )

    return tuple(
        GeneratedElementOrigin(item.origin, replacement)
        if item.generated is original
        else item
        for item in origins
    )


def _lower_class(
    declaration: ClassDeclaration,
    frontier: ArityFrontier,
    on_rewrite: TypeRewriteObserver | None = None,
) -> Result[tuple[ClassDeclaration, bool], LoweringError]:
    methods: list[FunctionDeclaration | OverloadDeclaration] = []
    has_overloads = False
    for method in declaration.methods:
        if isinstance(method, OverloadDeclaration):
            methods.append(method)
            has_overloads = True
            continue

        lowered = _lower_function(method, frontier, on_rewrite=on_rewrite)
        if isinstance(lowered, Failure):
            return lowered

        lowered_method = lowered.unwrap()
        methods.append(lowered_method)
        has_overloads = has_overloads or isinstance(lowered_method, OverloadDeclaration)

    return Success((replace(declaration, methods=tuple(methods)), has_overloads))


def _lower_function(
    declaration: FunctionDeclaration,
    frontier: ArityFrontier,
    on_rewrite: TypeRewriteObserver | None = None,
) -> Result[FunctionDeclaration | OverloadDeclaration, LoweringError]:
    if isinstance(declaration.return_type, MapType):
        return _lower_map_function(
            declaration, declaration.return_type, on_rewrite=on_rewrite
        )

    return _lower_each_function(declaration, frontier, on_rewrite=on_rewrite)


def _lower_each_function(
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

    captured_names = _collect_variable_names(each_annotation.item)
    if len(captured_names) != 1:
        return Failure(
            LoweringError(
                LoweringErrorCode.MISSING_CAPTURE,
                declaration.name,
                "Each must contain exactly one type variable",
            )
        )

    captured_name = captured_names[0]
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
class PredicateMatch:
    input_type: StubTypeExpression
    result: bool


def _lower_map_function(
    declaration: FunctionDeclaration,
    mapping: MapType,
    on_rewrite: TypeRewriteObserver | None = None,
) -> Result[FunctionDeclaration | OverloadDeclaration, LoweringError]:
    if not isinstance(mapping.subject, TypeVariable):
        return Failure(
            LoweringError(
                LoweringErrorCode.MISSING_CONTROLLER,
                declaration.name,
                "Map subject must be a type parameter at a callable boundary",
            )
        )

    controller = mapping.subject.name
    if not _function_has_controller(declaration, controller):
        return Failure(
            LoweringError(
                LoweringErrorCode.MISSING_CONTROLLER,
                declaration.name,
                f"no parameter is controlled by {controller}",
            )
        )

    seen: set[StubTypeExpression | Predicate] = set()
    for case in mapping.cases:
        if case.test in seen:
            return Failure(
                LoweringError(
                    LoweringErrorCode.DUPLICATE_MAP_CASE,
                    declaration.name,
                    "Map case tests must be unique",
                )
            )

        seen.add(case.test)
        if is_predicate(case.test):
            predicate_controller_result = predicate_controller(case.test)
            if (
                isinstance(predicate_controller_result, Failure)
                or predicate_controller_result.unwrap() != controller
                or not predicate_is_supported(case.test, controller)
            ):
                return Failure(
                    LoweringError(
                        LoweringErrorCode.UNSUPPORTED_PREDICATE,
                        declaration.name,
                        "Map predicate cases must compare the subject type parameter "
                        "to concrete types at a callable boundary",
                    )
                )

    specializations = map_specializations(mapping, controller)
    signatures = tuple(
        _specialized_signature(
            declaration,
            controller,
            case.test,
            _substitute(case.output_type, controller, case.test, on_rewrite=on_rewrite),
            on_rewrite=on_rewrite,
        )
        for case in specializations
        if not is_predicate(case.test)
    )
    fallback = replace(
        declaration,
        return_type=_union(
            (*(case.output_type for case in mapping.cases), mapping.default),
            on_rewrite=on_rewrite,
        ),
    )
    if on_rewrite is not None:
        for signature in (*signatures, fallback):
            on_rewrite(mapping, signature.return_type)

    if not signatures:
        return Success(fallback)

    return Success(OverloadDeclaration(signatures, fallback))


def map_specializations(mapping: MapType, controller: str) -> tuple[MapCase, ...]:
    candidates: list[StubTypeExpression] = []
    for case in mapping.cases:
        tests = (
            tuple(
                match.input_type for match in predicate_matches(case.test, controller)
            )
            if is_predicate(case.test)
            else (case.test,)
        )
        for test in tests:
            if test not in candidates:
                candidates.append(test)

    return tuple(
        MapCase(candidate, _map_output_for_input(mapping, controller, candidate))
        for candidate in candidates
    )


def map_default_output(mapping: MapType, controller: str) -> StubTypeExpression:
    return next(
        (
            case.output_type
            for case in mapping.cases
            if is_predicate(case.test)
            and _predicate_result_for_input(
                case.test,
                controller,
                TypeVariable(controller),
            )
        ),
        mapping.default,
    )


def _map_output_for_input(
    mapping: MapType,
    controller: str,
    input_type: StubTypeExpression,
) -> StubTypeExpression:
    for case in mapping.cases:
        matched = (
            _predicate_result_for_input(case.test, controller, input_type)
            if is_predicate(case.test)
            else case.test == input_type
        )
        if matched:
            return case.output_type

    return mapping.default


def _predicate_result_for_input(
    predicate: Predicate,
    controller: str,
    input_type: StubTypeExpression,
) -> bool:
    resolved = _resolve_predicate_for_input(predicate, controller, input_type)
    if resolved is not None:
        return resolved

    match = next(
        (
            candidate
            for candidate in predicate_matches(predicate, controller)
            if candidate.input_type == input_type
        ),
        None,
    )
    return predicate_default(predicate) if match is None else match.result


def _resolve_predicate_for_input(
    predicate: Predicate,
    controller: str,
    input_type: StubTypeExpression,
) -> bool | None:
    match predicate:
        case EqualPredicate(left, right):
            return _substitute(left, controller, input_type) == _substitute(
                right, controller, input_type
            )
        case AssignablePredicate(source, target):
            return _known_assignability(
                _substitute(source, controller, input_type),
                _substitute(target, controller, input_type),
            )
        case AllPredicate(predicates):
            values = tuple(
                _resolve_predicate_for_input(item, controller, input_type)
                for item in predicates
            )
            if False in values:
                return False

            return True if all(value is True for value in values) else None
        case AnyPredicate(predicates):
            values = tuple(
                _resolve_predicate_for_input(item, controller, input_type)
                for item in predicates
            )
            if True in values:
                return True

            return False if all(value is False for value in values) else None
        case NotPredicate(item):
            value = _resolve_predicate_for_input(item, controller, input_type)
            return None if value is None else not value


def _known_assignability(
    source: StubTypeExpression,
    target: StubTypeExpression,
) -> bool | None:
    if source == target or target == TypeName("object"):
        return True

    if isinstance(source, UnionExpression):
        values = tuple(
            _known_assignability(member, target) for member in source.members
        )
        if False in values:
            return False

        return True if all(value is True for value in values) else None

    if isinstance(target, UnionExpression):
        values = tuple(
            _known_assignability(source, member) for member in target.members
        )
        if True in values:
            return True

        return False if all(value is False for value in values) else None

    return (
        None
        if _collect_variable_names(source) or _collect_variable_names(target)
        else False
    )


def predicate_default(predicate: Predicate) -> bool:
    if isinstance(predicate, NotPredicate):
        return not predicate_default(predicate.predicate)

    if isinstance(predicate, AllPredicate):
        return all(predicate_default(item) for item in predicate.predicates)

    if isinstance(predicate, AnyPredicate):
        return any(predicate_default(item) for item in predicate.predicates)

    return False


def _specialized_signature(
    declaration: FunctionDeclaration,
    controller: str,
    input_type: StubTypeExpression,
    return_type: StubTypeExpression,
    on_rewrite: TypeRewriteObserver | None = None,
) -> FunctionDeclaration:
    return replace(
        declaration,
        parameters=tuple(
            replace(
                parameter,
                annotation=_substitute(
                    parameter.annotation, controller, input_type, on_rewrite=on_rewrite
                ),
            )
            for parameter in declaration.parameters
        ),
        return_type=_substitute(
            return_type, controller, input_type, on_rewrite=on_rewrite
        ),
        type_parameters=tuple(
            item
            for item in declaration.type_parameters
            if _type_parameter_name(item) != controller
        ),
    )


def predicate_controller(
    predicate: Predicate,
) -> Result[str, LoweringErrorCode]:
    names = _predicate_variable_names(predicate)
    if len(names) != 1:
        return Failure(LoweringErrorCode.UNSUPPORTED_PREDICATE)

    return Success(names[0])


def _predicate_variable_names(predicate: Predicate) -> tuple[str, ...]:
    names: list[str] = []

    def add(expression: StubTypeExpression) -> None:
        for name in _collect_variable_names(expression):
            if name not in names:
                names.append(name)

    def visit(current: Predicate) -> None:
        if isinstance(current, EqualPredicate):
            add(current.left)
            add(current.right)
        elif isinstance(current, AssignablePredicate):
            add(current.source)
            add(current.target)
        elif isinstance(current, AllPredicate | AnyPredicate):
            for child in current.predicates:
                visit(child)
        else:
            visit(current.predicate)

    visit(predicate)
    return tuple(names)


def predicate_matches(
    predicate: Predicate, controller: str
) -> tuple[PredicateMatch, ...]:
    if isinstance(predicate, EqualPredicate):
        if predicate.left == TypeVariable(controller) and not _has_variable(
            predicate.right, controller
        ):
            return (PredicateMatch(predicate.right, True),)

        if predicate.right == TypeVariable(controller) and not _has_variable(
            predicate.left, controller
        ):
            return (PredicateMatch(predicate.left, True),)

        return ()

    if isinstance(predicate, AssignablePredicate):
        if predicate.source == TypeVariable(controller) and not _has_variable(
            predicate.target, controller
        ):
            return (PredicateMatch(predicate.target, True),)

        return ()

    if isinstance(predicate, NotPredicate):
        return tuple(
            PredicateMatch(match.input_type, not match.result)
            for match in predicate_matches(predicate.predicate, controller)
        )

    child_matches = tuple(
        predicate_matches(child, controller) for child in predicate.predicates
    )
    if isinstance(predicate, AllPredicate):
        true_matches = _common_matches(child_matches, True)
        false_matches = _matching_results(child_matches, False)
        return _unique_matches((*true_matches, *false_matches))

    true_matches = _matching_results(child_matches, True)
    false_matches = _common_matches(child_matches, False)
    return _unique_matches((*true_matches, *false_matches))


def predicate_is_supported(predicate: Predicate, controller: str) -> bool:
    variable = TypeVariable(controller)
    if isinstance(predicate, EqualPredicate):
        return (
            predicate.left == variable
            and not _has_variable(predicate.right, controller)
        ) or (
            predicate.right == variable
            and not _has_variable(predicate.left, controller)
        )

    if isinstance(predicate, AssignablePredicate):
        return predicate.source == variable and not _has_variable(
            predicate.target, controller
        )

    if isinstance(predicate, NotPredicate):
        return predicate_is_supported(predicate.predicate, controller)

    return all(
        predicate_is_supported(child, controller) for child in predicate.predicates
    )


def _matching_results(
    groups: tuple[tuple[PredicateMatch, ...], ...], result: bool
) -> tuple[PredicateMatch, ...]:
    return tuple(match for group in groups for match in group if match.result is result)


def _common_matches(
    groups: tuple[tuple[PredicateMatch, ...], ...], result: bool
) -> tuple[PredicateMatch, ...]:
    if not groups:
        return ()

    first = tuple(match for match in groups[0] if match.result is result)
    return tuple(
        match
        for match in first
        if all(
            any(
                candidate.result is result and candidate.input_type == match.input_type
                for candidate in group
            )
            for group in groups[1:]
        )
    )


def _unique_matches(
    matches: tuple[PredicateMatch, ...],
) -> tuple[PredicateMatch, ...]:
    unique: list[PredicateMatch] = []
    for match in matches:
        if match not in unique:
            unique.append(match)

    return tuple(unique)


def _function_has_controller(declaration: FunctionDeclaration, controller: str) -> bool:
    return any(
        _has_variable(parameter.annotation, controller)
        for parameter in declaration.parameters
    )


def _has_variable(expression: StubTypeExpression, variable: str) -> bool:
    return variable in _collect_variable_names(expression)


def _union(
    expressions: tuple[StubTypeExpression, ...],
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    members: list[StubTypeExpression] = []
    for expression in expressions:
        candidates = (
            expression.members
            if isinstance(expression, UnionExpression)
            else (expression,)
        )
        for candidate in candidates:
            if on_rewrite is not None and candidate is not expression:
                on_rewrite(expression, candidate)

            retained = next((member for member in members if member == candidate), None)
            if retained is None:
                members.append(candidate)
            elif on_rewrite is not None:
                for original, replacement in zip(
                    walk_type(candidate), walk_type(retained), strict=True
                ):
                    on_rewrite(original, replacement)

    if len(members) == 1:
        return members[0]

    return UnionExpression(tuple(members))


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
    generated_names = _fresh_type_parameter_names(
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
            annotation = _substitute(
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
        if _type_parameter_name(parameter) != captured_name
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
    cases = tuple(
        _StructuralMapChoice(
            _replace_map_value(case.test, generated_type, on_rewrite=on_rewrite),
            _replace_map_value(case.output_type, generated_type, on_rewrite=on_rewrite),
            False,
        )
        for case in map_specializations(mapping, controller)
        if not is_predicate(case.test)
    )
    return (
        *cases,
        _StructuralMapChoice(
            generated_type,
            _substitute(
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


def _replace_map_value(
    expression: StubTypeExpression,
    replacement: StubTypeExpression,
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    result = _replace_map_value_expression(expression, replacement, on_rewrite)
    if on_rewrite is not None:
        on_rewrite(expression, result)

    return result


def _replace_map_value_expression(
    expression: StubTypeExpression,
    replacement: StubTypeExpression,
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    if isinstance(expression, MapValueType):
        return replacement

    if isinstance(expression, TypeApplication | FixedTuple | UnionExpression):
        return rewrite_type_children(
            expression,
            lambda child: _replace_map_value(child, replacement, on_rewrite=on_rewrite),
        )

    return expression


def _fallback_signature(
    declaration: FunctionDeclaration, on_rewrite: TypeRewriteObserver | None = None
) -> FunctionDeclaration:
    type_var_tuples = frozenset(
        _type_parameter_name(parameter)
        for parameter in declaration.type_parameters
        if parameter.lstrip().startswith("*")
    )
    transformed_type_var_tuples = frozenset(
        name
        for parameter in declaration.parameters
        if isinstance(parameter.annotation, EachType)
        and not isinstance(parameter.annotation.item, TypeVariable)
        for name in _collect_variable_names(parameter.annotation.item)
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
            if _type_parameter_name(parameter) not in transformed_type_var_tuples
        ),
    )


def _expanded_parameter_kind(
    preceding: tuple[Parameter, ...],
) -> ParameterKind:
    if all(parameter.kind is ParameterKind.POSITIONAL_ONLY for parameter in preceding):
        return ParameterKind.POSITIONAL_ONLY

    return ParameterKind.POSITIONAL_OR_KEYWORD


def _fresh_type_parameter_names(
    base: str, count: int, reserved: tuple[str, ...]
) -> tuple[str, ...]:
    names: list[str] = []
    reserved_names = {_type_parameter_name(item) for item in reserved}
    candidate_index = 1
    while len(names) < count:
        candidate = f"{base}{candidate_index}"
        candidate_index += 1
        if candidate in reserved_names:
            continue

        names.append(candidate)
        reserved_names.add(candidate)

    return tuple(names)


def _type_parameter_name(declaration: str) -> str:
    return declaration.lstrip("*").split(":", 1)[0].split("=", 1)[0].strip()


def _collect_variable_names(expression: StubTypeExpression) -> tuple[str, ...]:
    names: list[str] = []

    def visit(current: StubTypeExpression) -> None:
        if isinstance(current, TypeVariable):
            if current.name not in names:
                names.append(current.name)
        elif isinstance(current, TypeApplication):
            visit(current.constructor)
            for argument in current.arguments:
                visit(argument)
        elif isinstance(current, FixedTuple):
            for item in current.items:
                visit(item)
        elif isinstance(current, UnionExpression):
            for member in current.members:
                visit(member)
        elif isinstance(
            current, HomogeneousTuple | EachType | CollectType | SchemaType
        ):
            visit(current.item)

    visit(expression)
    return tuple(names)


def _substitute(
    expression: StubTypeExpression,
    variable: str,
    replacement: StubTypeExpression,
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    result = _substitute_expression(expression, variable, replacement, on_rewrite)
    if on_rewrite is not None:
        on_rewrite(expression, result)

    return result


def _substitute_expression(
    expression: StubTypeExpression,
    variable: str,
    replacement: StubTypeExpression,
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    if isinstance(expression, TypeVariable):
        return replacement if expression.name == variable else expression

    if isinstance(
        expression,
        TypeApplication | FixedTuple | HomogeneousTuple | SchemaType | UnionExpression,
    ):
        return rewrite_type_children(
            expression,
            lambda child: _substitute(
                child, variable, replacement, on_rewrite=on_rewrite
            ),
        )

    return expression


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
            item = _substitute(item, name, TypeName("object"), on_rewrite=on_rewrite)

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

    if isinstance(expression, SchemaType):
        return _erase_markers(
            expression.item,
            type_var_tuples,
            broad_type_var_tuples,
            on_rewrite=on_rewrite,
        )

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
        return _union(
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


def _module_contains_literal(module: StubModule) -> bool:
    return any(_declaration_contains_literal(item) for item in module.declarations)


def _declaration_contains_literal(declaration: Declaration) -> bool:
    if isinstance(declaration, FunctionDeclaration):
        return _function_contains_literal(declaration)

    if isinstance(declaration, TypeAliasDeclaration):
        return _contains_literal(declaration.value)

    if isinstance(declaration, VariableDeclaration):
        return _contains_literal(declaration.annotation)

    if isinstance(declaration, ClassDeclaration):
        fields_contain_literal = any(
            _contains_literal(field.annotation) for field in declaration.fields
        )
        methods_contain_literal = any(
            _function_contains_literal(method)
            if isinstance(method, FunctionDeclaration)
            else any(_function_contains_literal(item) for item in method.signatures)
            or _function_contains_literal(method.fallback)
            for method in declaration.methods
        )
        return fields_contain_literal or methods_contain_literal

    return any(_function_contains_literal(item) for item in declaration.signatures) or (
        _function_contains_literal(declaration.fallback)
    )


def _function_contains_literal(declaration: FunctionDeclaration) -> bool:
    return _contains_literal(declaration.return_type) or any(
        _contains_literal(parameter.annotation) for parameter in declaration.parameters
    )


def _contains_literal(expression: StubTypeExpression) -> bool:
    if isinstance(expression, LiteralType):
        return True

    if isinstance(expression, TypeApplication):
        return _contains_literal(expression.constructor) or any(
            _contains_literal(argument) for argument in expression.arguments
        )

    if isinstance(expression, FixedTuple):
        return any(_contains_literal(item) for item in expression.items)

    if isinstance(expression, UnionExpression):
        return any(_contains_literal(member) for member in expression.members)

    if isinstance(expression, HomogeneousTuple | EachType | CollectType):
        return _contains_literal(expression.item)

    if isinstance(expression, UnpackedType):
        return _contains_literal(expression.item)

    return False


def _add_import(
    imports: tuple[ModuleImport, ...], required: ImportFrom
) -> tuple[ModuleImport, ...]:
    return (
        *(item for item in imports if isinstance(item, Import)),
        *sorted(
            item
            for item in merge_imports((*imports, required))
            if isinstance(item, ImportFrom)
        ),
    )
