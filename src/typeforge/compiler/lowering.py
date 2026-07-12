from dataclasses import dataclass
from enum import StrEnum
from itertools import product

from typeforge._result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class TypeName:
    name: str


@dataclass(frozen=True, slots=True)
class TypeVariable:
    name: str


@dataclass(frozen=True, slots=True)
class TypeApplication:
    constructor: TypeExpression
    arguments: tuple[TypeExpression, ...]


@dataclass(frozen=True, slots=True)
class FixedTuple:
    items: tuple[TypeExpression, ...]


@dataclass(frozen=True, slots=True)
class HomogeneousTuple:
    item: TypeExpression


@dataclass(frozen=True, slots=True)
class EachType:
    item: TypeExpression


@dataclass(frozen=True, slots=True)
class CollectType:
    item: TypeExpression


@dataclass(frozen=True, slots=True)
class UnpackedType:
    item: TypeExpression


@dataclass(frozen=True, slots=True)
class LiteralType:
    value: str | bytes | int | bool | None


@dataclass(frozen=True, slots=True)
class UnionExpression:
    members: tuple[TypeExpression, ...]


@dataclass(frozen=True, slots=True)
class EqualPredicate:
    left: TypeExpression
    right: TypeExpression


@dataclass(frozen=True, slots=True)
class AssignablePredicate:
    source: TypeExpression
    target: TypeExpression


@dataclass(frozen=True, slots=True)
class AllPredicate:
    predicates: tuple[Predicate, ...]


@dataclass(frozen=True, slots=True)
class AnyPredicate:
    predicates: tuple[Predicate, ...]


@dataclass(frozen=True, slots=True)
class NotPredicate:
    predicate: Predicate


type Predicate = (
    EqualPredicate | AssignablePredicate | AllPredicate | AnyPredicate | NotPredicate
)


@dataclass(frozen=True, slots=True)
class IfType:
    condition: Predicate
    when_true: TypeExpression
    when_false: TypeExpression


@dataclass(frozen=True, slots=True)
class MapCase:
    input_type: TypeExpression
    output_type: TypeExpression


@dataclass(frozen=True, slots=True)
class MapType:
    subject: TypeExpression
    cases: tuple[MapCase, ...]
    default: TypeExpression


@dataclass(frozen=True, slots=True)
class MapValueType:
    pass


@dataclass(frozen=True, slots=True)
class FieldType:
    name: TypeExpression
    value: TypeExpression
    required: bool = True
    readonly: bool = False


@dataclass(frozen=True, slots=True)
class MapFieldsType:
    record: TypeExpression
    transform: TypeExpression


type TypeExpression = (
    TypeName
    | TypeVariable
    | TypeApplication
    | FixedTuple
    | HomogeneousTuple
    | EachType
    | CollectType
    | UnpackedType
    | LiteralType
    | UnionExpression
    | IfType
    | MapType
    | MapValueType
    | FieldType
    | MapFieldsType
)


class ParameterKind(StrEnum):
    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    annotation: TypeExpression
    kind: ParameterKind = ParameterKind.POSITIONAL_OR_KEYWORD
    default: str | None = None


@dataclass(frozen=True, slots=True)
class FunctionDeclaration:
    name: str
    parameters: tuple[Parameter, ...]
    return_type: TypeExpression
    type_parameters: tuple[str, ...] = ()
    is_async: bool = False
    decorators: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OverloadDeclaration:
    signatures: tuple[FunctionDeclaration, ...]
    fallback: FunctionDeclaration


@dataclass(frozen=True, slots=True)
class TypeAliasDeclaration:
    name: str
    value: TypeExpression
    type_parameters: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassField:
    name: str
    annotation: TypeExpression
    default: str | None = None


@dataclass(frozen=True, slots=True)
class ClassDeclaration:
    name: str
    bases: tuple[TypeExpression, ...]
    fields: tuple[ClassField, ...]
    methods: tuple[FunctionDeclaration | OverloadDeclaration, ...]
    type_parameters: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    decorators: tuple[str, ...] = ()


type Declaration = (
    FunctionDeclaration | OverloadDeclaration | TypeAliasDeclaration | ClassDeclaration
)


@dataclass(frozen=True, slots=True, order=True)
class ImportFrom:
    module: str
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StubModule:
    name: str
    declarations: tuple[Declaration, ...]
    imports: tuple[ImportFrom, ...] = ()


@dataclass(frozen=True, slots=True)
class ArityFrontier:
    minimum: int = 0
    maximum: int = 8


class LoweringErrorCode(StrEnum):
    INVALID_FRONTIER = "invalid_frontier"
    INVALID_EACH_POSITION = "invalid_each_position"
    MISSING_CAPTURE = "missing_capture"
    MULTIPLE_CAPTURES = "multiple_captures"
    MISSING_CONTROLLER = "missing_controller"
    UNSUPPORTED_PREDICATE = "unsupported_predicate"
    DUPLICATE_MAP_CASE = "duplicate_map_case"


@dataclass(frozen=True, slots=True)
class LoweringError:
    code: LoweringErrorCode
    declaration: str
    message: str


def lower_variadic_module(
    module: StubModule, frontier: ArityFrontier
) -> Result[StubModule, LoweringError]:
    if frontier.minimum < 0 or frontier.maximum < frontier.minimum:
        return Err(
            LoweringError(
                LoweringErrorCode.INVALID_FRONTIER,
                module.name,
                "arity frontier must satisfy 0 <= minimum <= maximum",
            )
        )

    lowered: list[Declaration] = []
    has_overloads = False
    for declaration in module.declarations:
        if isinstance(declaration, ClassDeclaration):
            class_result = _lower_class(declaration, frontier)
            if isinstance(class_result, Err):
                return class_result
            lowered_class, class_has_overloads = class_result.value
            has_overloads = has_overloads or class_has_overloads
            lowered.append(lowered_class)
            continue
        if not isinstance(declaration, FunctionDeclaration):
            lowered.append(declaration)
            continue
        result = _lower_function(declaration, frontier)
        if isinstance(result, Err):
            return result
        lowered_declaration = result.value
        has_overloads = has_overloads or isinstance(
            lowered_declaration, OverloadDeclaration
        )
        lowered.append(lowered_declaration)

    imports = module.imports
    if has_overloads:
        imports = _add_import(imports, ImportFrom("typing", ("overload",)))
    lowered_module = StubModule(module.name, tuple(lowered), imports)
    if _module_contains_literal(lowered_module):
        lowered_module = StubModule(
            lowered_module.name,
            lowered_module.declarations,
            _add_import(lowered_module.imports, ImportFrom("typing", ("Literal",))),
        )
    return Ok(lowered_module)


def _lower_class(
    declaration: ClassDeclaration, frontier: ArityFrontier
) -> Result[tuple[ClassDeclaration, bool], LoweringError]:
    methods: list[FunctionDeclaration | OverloadDeclaration] = []
    has_overloads = False
    for method in declaration.methods:
        if isinstance(method, OverloadDeclaration):
            methods.append(method)
            has_overloads = True
            continue
        lowered = _lower_function(method, frontier)
        if isinstance(lowered, Err):
            return lowered
        if isinstance(lowered.value, TypeAliasDeclaration | ClassDeclaration):
            raise AssertionError(
                "function lowering produced a non-callable declaration"
            )
        methods.append(lowered.value)
        has_overloads = has_overloads or isinstance(lowered.value, OverloadDeclaration)
    return Ok(
        (
            ClassDeclaration(
                name=declaration.name,
                bases=declaration.bases,
                fields=declaration.fields,
                methods=tuple(methods),
                type_parameters=declaration.type_parameters,
                keywords=declaration.keywords,
                decorators=declaration.decorators,
            ),
            has_overloads,
        )
    )


def _lower_function(
    declaration: FunctionDeclaration, frontier: ArityFrontier
) -> Result[Declaration, LoweringError]:
    if isinstance(declaration.return_type, IfType):
        return _lower_if_function(declaration, declaration.return_type)
    if isinstance(declaration.return_type, MapType):
        return _lower_map_function(declaration, declaration.return_type)
    return _lower_each_function(declaration, frontier)


def _lower_each_function(
    declaration: FunctionDeclaration, frontier: ArityFrontier
) -> Result[Declaration, LoweringError]:
    each_parameters = tuple(
        parameter
        for parameter in declaration.parameters
        if isinstance(parameter.annotation, EachType)
    )
    if not each_parameters:
        return Ok(declaration)
    if len(each_parameters) != 1:
        return Err(
            LoweringError(
                LoweringErrorCode.MULTIPLE_CAPTURES,
                declaration.name,
                "a function must contain exactly one Each parameter",
            )
        )

    each_parameter = each_parameters[0]
    each_annotation = each_parameter.annotation
    if not isinstance(each_annotation, EachType):
        return Ok(declaration)
    if each_parameter.kind is not ParameterKind.VAR_POSITIONAL:
        return Err(
            LoweringError(
                LoweringErrorCode.INVALID_EACH_POSITION,
                declaration.name,
                "Each must annotate a variadic positional parameter",
            )
        )

    captured_names = _collect_variable_names(each_annotation.item)
    if len(captured_names) != 1:
        return Err(
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
        )
    )
    fallback = _fallback_signature(declaration)
    return Ok(OverloadDeclaration(signatures, fallback))


@dataclass(frozen=True, slots=True)
class _PredicateMatch:
    input_type: TypeExpression
    result: bool


def _lower_if_function(
    declaration: FunctionDeclaration, conditional: IfType
) -> Result[Declaration, LoweringError]:
    controller = _predicate_controller(conditional.condition)
    if isinstance(controller, Err):
        return Err(
            LoweringError(
                controller.error,
                declaration.name,
                "conditional predicate must compare one type parameter "
                "to a concrete type",
            )
        )
    if not _function_has_controller(declaration, controller.value):
        return Err(
            LoweringError(
                LoweringErrorCode.MISSING_CONTROLLER,
                declaration.name,
                f"no parameter is controlled by {controller.value}",
            )
        )
    if not _predicate_is_supported(conditional.condition, controller.value):
        return Err(
            LoweringError(
                LoweringErrorCode.UNSUPPORTED_PREDICATE,
                declaration.name,
                "predicate cannot be represented at a callable boundary",
            )
        )
    matches = _predicate_matches(conditional.condition, controller.value)
    signatures = tuple(
        _specialized_signature(
            declaration,
            controller.value,
            match.input_type,
            conditional.when_true if match.result else conditional.when_false,
        )
        for match in matches
    )
    fallback = _replace_return(
        declaration,
        _union((conditional.when_true, conditional.when_false)),
    )
    if not signatures:
        return Ok(fallback)
    return Ok(OverloadDeclaration(signatures, fallback))


def _lower_map_function(
    declaration: FunctionDeclaration, mapping: MapType
) -> Result[Declaration, LoweringError]:
    if not isinstance(mapping.subject, TypeVariable):
        return Err(
            LoweringError(
                LoweringErrorCode.MISSING_CONTROLLER,
                declaration.name,
                "Map subject must be a type parameter at a callable boundary",
            )
        )
    controller = mapping.subject.name
    if not _function_has_controller(declaration, controller):
        return Err(
            LoweringError(
                LoweringErrorCode.MISSING_CONTROLLER,
                declaration.name,
                f"no parameter is controlled by {controller}",
            )
        )
    seen: set[TypeExpression] = set()
    for case in mapping.cases:
        if case.input_type in seen:
            return Err(
                LoweringError(
                    LoweringErrorCode.DUPLICATE_MAP_CASE,
                    declaration.name,
                    "Map input types must be unique",
                )
            )
        seen.add(case.input_type)
    signatures = tuple(
        _specialized_signature(
            declaration,
            controller,
            case.input_type,
            _substitute(case.output_type, controller, case.input_type),
        )
        for case in mapping.cases
    )
    fallback = _replace_return(
        declaration,
        _union((*tuple(case.output_type for case in mapping.cases), mapping.default)),
    )
    if not signatures:
        return Ok(fallback)
    return Ok(OverloadDeclaration(signatures, fallback))


def _specialized_signature(
    declaration: FunctionDeclaration,
    controller: str,
    input_type: TypeExpression,
    return_type: TypeExpression,
) -> FunctionDeclaration:
    return FunctionDeclaration(
        declaration.name,
        tuple(
            Parameter(
                parameter.name,
                _substitute(parameter.annotation, controller, input_type),
                parameter.kind,
                parameter.default,
            )
            for parameter in declaration.parameters
        ),
        _substitute(return_type, controller, input_type),
        tuple(
            item
            for item in declaration.type_parameters
            if _type_parameter_name(item) != controller
        ),
        declaration.is_async,
        declaration.decorators,
    )


def _replace_return(
    declaration: FunctionDeclaration, return_type: TypeExpression
) -> FunctionDeclaration:
    return FunctionDeclaration(
        declaration.name,
        declaration.parameters,
        return_type,
        declaration.type_parameters,
        declaration.is_async,
        declaration.decorators,
    )


def _predicate_controller(
    predicate: Predicate,
) -> Result[str, LoweringErrorCode]:
    names = _predicate_variable_names(predicate)
    if len(names) != 1:
        return Err(LoweringErrorCode.UNSUPPORTED_PREDICATE)
    return Ok(names[0])


def _predicate_variable_names(predicate: Predicate) -> tuple[str, ...]:
    names: list[str] = []

    def add(expression: TypeExpression) -> None:
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


def _predicate_matches(
    predicate: Predicate, controller: str
) -> tuple[_PredicateMatch, ...]:
    if isinstance(predicate, EqualPredicate):
        if predicate.left == TypeVariable(controller) and not _has_variable(
            predicate.right, controller
        ):
            return (_PredicateMatch(predicate.right, True),)
        if predicate.right == TypeVariable(controller) and not _has_variable(
            predicate.left, controller
        ):
            return (_PredicateMatch(predicate.left, True),)
        return ()
    if isinstance(predicate, AssignablePredicate):
        if predicate.source == TypeVariable(controller) and not _has_variable(
            predicate.target, controller
        ):
            return (_PredicateMatch(predicate.target, True),)
        return ()
    if isinstance(predicate, NotPredicate):
        return tuple(
            _PredicateMatch(match.input_type, not match.result)
            for match in _predicate_matches(predicate.predicate, controller)
        )

    child_matches = tuple(
        _predicate_matches(child, controller) for child in predicate.predicates
    )
    if isinstance(predicate, AllPredicate):
        true_matches = _common_matches(child_matches, True)
        false_matches = _matching_results(child_matches, False)
        return _unique_matches((*true_matches, *false_matches))
    true_matches = _matching_results(child_matches, True)
    false_matches = _common_matches(child_matches, False)
    return _unique_matches((*true_matches, *false_matches))


def _predicate_is_supported(predicate: Predicate, controller: str) -> bool:
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
        return _predicate_is_supported(predicate.predicate, controller)
    return all(
        _predicate_is_supported(child, controller) for child in predicate.predicates
    )


def _matching_results(
    groups: tuple[tuple[_PredicateMatch, ...], ...], result: bool
) -> tuple[_PredicateMatch, ...]:
    return tuple(match for group in groups for match in group if match.result is result)


def _common_matches(
    groups: tuple[tuple[_PredicateMatch, ...], ...], result: bool
) -> tuple[_PredicateMatch, ...]:
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
    matches: tuple[_PredicateMatch, ...],
) -> tuple[_PredicateMatch, ...]:
    unique: list[_PredicateMatch] = []
    for match in matches:
        if match not in unique:
            unique.append(match)
    return tuple(unique)


def _function_has_controller(declaration: FunctionDeclaration, controller: str) -> bool:
    return any(
        _has_variable(parameter.annotation, controller)
        for parameter in declaration.parameters
    )


def _has_variable(expression: TypeExpression, variable: str) -> bool:
    return variable in _collect_variable_names(expression)


def _union(expressions: tuple[TypeExpression, ...]) -> TypeExpression:
    members: list[TypeExpression] = []
    for expression in expressions:
        candidates = (
            expression.members
            if isinstance(expression, UnionExpression)
            else (expression,)
        )
        for candidate in candidates:
            if candidate not in members:
                members.append(candidate)
    if len(members) == 1:
        return members[0]
    return UnionExpression(tuple(members))


@dataclass(frozen=True, slots=True)
class _StructuralMapChoice:
    input_type: TypeExpression
    output_type: TypeExpression
    is_default: bool


def _expand_signatures(
    declaration: FunctionDeclaration,
    each_parameter: Parameter,
    argument_pattern: TypeExpression,
    captured_name: str,
    arity: int,
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
            ),
        )
    choices = tuple(
        tuple(_structural_map_choices(structural_map, generated_type))
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
        )
        for combination in ordered
    )


def _expand_signature_with_types(
    declaration: FunctionDeclaration,
    each_parameter: Parameter,
    argument_pattern: TypeExpression,
    captured_name: str,
    generated_names: tuple[str, ...],
    captured_inputs: tuple[TypeExpression, ...],
    collected_outputs: tuple[TypeExpression, ...],
) -> FunctionDeclaration:
    expanded_parameters: list[Parameter] = []
    for parameter in declaration.parameters:
        if parameter is not each_parameter:
            expanded_parameters.append(parameter)
            continue
        positional_kind = _expanded_parameter_kind(tuple(expanded_parameters))
        expanded_parameters.extend(
            Parameter(
                f"{each_parameter.name}_{index}",
                _substitute(argument_pattern, captured_name, item),
                positional_kind,
            )
            for index, item in enumerate(captured_inputs, start=1)
        )

    retained = tuple(
        parameter
        for parameter in declaration.type_parameters
        if _type_parameter_name(parameter) != captured_name
    )
    return FunctionDeclaration(
        declaration.name,
        tuple(expanded_parameters),
        _substitute_collect(declaration.return_type, captured_name, collected_outputs),
        retained + generated_names,
        declaration.is_async,
        declaration.decorators,
    )


def _find_collected_map(
    expression: TypeExpression, captured_name: str
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
    mapping: MapType, generated_type: TypeVariable
) -> tuple[_StructuralMapChoice, ...]:
    cases = tuple(
        _StructuralMapChoice(
            _replace_map_value(case.input_type, generated_type),
            _replace_map_value(case.output_type, generated_type),
            False,
        )
        for case in mapping.cases
    )
    return (
        *cases,
        _StructuralMapChoice(
            generated_type,
            _substitute(mapping.default, _map_subject_name(mapping), generated_type),
            True,
        ),
    )


def _map_subject_name(mapping: MapType) -> str:
    if isinstance(mapping.subject, TypeVariable):
        return mapping.subject.name
    return ""


def _replace_map_value(
    expression: TypeExpression, replacement: TypeExpression
) -> TypeExpression:
    if isinstance(expression, MapValueType):
        return replacement
    if isinstance(expression, TypeApplication):
        return TypeApplication(
            _replace_map_value(expression.constructor, replacement),
            tuple(
                _replace_map_value(argument, replacement)
                for argument in expression.arguments
            ),
        )
    if isinstance(expression, FixedTuple):
        return FixedTuple(
            tuple(_replace_map_value(item, replacement) for item in expression.items)
        )
    if isinstance(expression, UnionExpression):
        return UnionExpression(
            tuple(
                _replace_map_value(member, replacement) for member in expression.members
            )
        )
    return expression


def _fallback_signature(declaration: FunctionDeclaration) -> FunctionDeclaration:
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
    return FunctionDeclaration(
        declaration.name,
        tuple(
            Parameter(
                parameter.name,
                _erase_markers(
                    parameter.annotation,
                    type_var_tuples,
                    transformed_type_var_tuples,
                ),
                parameter.kind,
                parameter.default,
            )
            for parameter in declaration.parameters
        ),
        _erase_markers(
            declaration.return_type,
            type_var_tuples,
            transformed_type_var_tuples,
        ),
        tuple(
            parameter
            for parameter in declaration.type_parameters
            if _type_parameter_name(parameter) not in transformed_type_var_tuples
        ),
        declaration.is_async,
        declaration.decorators,
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


def _collect_variable_names(expression: TypeExpression) -> tuple[str, ...]:
    names: list[str] = []

    def visit(current: TypeExpression) -> None:
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
        elif isinstance(current, HomogeneousTuple | EachType | CollectType):
            visit(current.item)

    visit(expression)
    return tuple(names)


def _substitute(
    expression: TypeExpression, variable: str, replacement: TypeExpression
) -> TypeExpression:
    if isinstance(expression, TypeVariable):
        return replacement if expression.name == variable else expression
    if isinstance(expression, TypeApplication):
        return TypeApplication(
            _substitute(expression.constructor, variable, replacement),
            tuple(
                _substitute(argument, variable, replacement)
                for argument in expression.arguments
            ),
        )
    if isinstance(expression, FixedTuple):
        return FixedTuple(
            tuple(_substitute(item, variable, replacement) for item in expression.items)
        )
    if isinstance(expression, HomogeneousTuple):
        return HomogeneousTuple(_substitute(expression.item, variable, replacement))
    if isinstance(expression, UnionExpression):
        return UnionExpression(
            tuple(
                _substitute(member, variable, replacement)
                for member in expression.members
            )
        )
    return expression


def _substitute_collect(
    expression: TypeExpression,
    variable: str,
    replacements: tuple[TypeExpression, ...],
) -> TypeExpression:
    if isinstance(expression, CollectType):
        if _collects_variable(expression.item, variable):
            return FixedTuple(replacements)
        return expression
    if isinstance(expression, TypeApplication):
        arguments: list[TypeExpression] = []
        for argument in expression.arguments:
            if (
                isinstance(argument, UnpackedType)
                and isinstance(argument.item, CollectType)
                and _collects_variable(argument.item.item, variable)
            ):
                arguments.extend(replacements)
            else:
                arguments.append(_substitute_collect(argument, variable, replacements))
        return TypeApplication(
            _substitute_collect(expression.constructor, variable, replacements),
            tuple(arguments),
        )
    if isinstance(expression, FixedTuple):
        return FixedTuple(
            tuple(
                _substitute_collect(item, variable, replacements)
                for item in expression.items
            )
        )
    if isinstance(expression, UnpackedType):
        return UnpackedType(
            _substitute_collect(expression.item, variable, replacements)
        )
    if isinstance(expression, UnionExpression):
        return UnionExpression(
            tuple(
                _substitute_collect(member, variable, replacements)
                for member in expression.members
            )
        )
    return expression


def _collects_variable(expression: TypeExpression, variable: str) -> bool:
    return expression == TypeVariable(variable) or (
        isinstance(expression, MapType) and expression.subject == TypeVariable(variable)
    )


def _erase_markers(
    expression: TypeExpression,
    type_var_tuples: frozenset[str] = frozenset(),
    broad_type_var_tuples: frozenset[str] = frozenset(),
) -> TypeExpression:
    if isinstance(expression, EachType):
        item = _erase_markers(expression.item, type_var_tuples, broad_type_var_tuples)
        for name in broad_type_var_tuples:
            item = _substitute(item, name, TypeName("object"))
        if isinstance(item, TypeVariable) and item.name in type_var_tuples:
            return UnpackedType(item)
        return item
    if isinstance(expression, CollectType):
        item = _erase_markers(expression.item, type_var_tuples, broad_type_var_tuples)
        if isinstance(item, TypeVariable) and item.name in broad_type_var_tuples:
            return HomogeneousTuple(TypeName("object"))
        if isinstance(item, TypeVariable) and item.name in type_var_tuples:
            return FixedTuple((UnpackedType(item),))
        return HomogeneousTuple(item)
    if isinstance(expression, MapType):
        return TypeName("object")
    if isinstance(expression, TypeApplication):
        return TypeApplication(
            _erase_markers(
                expression.constructor, type_var_tuples, broad_type_var_tuples
            ),
            tuple(
                _erase_markers(argument, type_var_tuples, broad_type_var_tuples)
                for argument in expression.arguments
            ),
        )
    if isinstance(expression, FixedTuple):
        return FixedTuple(
            tuple(
                _erase_markers(item, type_var_tuples, broad_type_var_tuples)
                for item in expression.items
            )
        )
    if isinstance(expression, HomogeneousTuple):
        return HomogeneousTuple(
            _erase_markers(expression.item, type_var_tuples, broad_type_var_tuples)
        )
    if isinstance(expression, UnpackedType):
        if isinstance(expression.item, CollectType):
            collected_item = _erase_markers(
                expression.item.item, type_var_tuples, broad_type_var_tuples
            )
            if (
                isinstance(collected_item, TypeVariable)
                and collected_item.name in broad_type_var_tuples
            ):
                return UnpackedType(HomogeneousTuple(TypeName("object")))
            if (
                isinstance(collected_item, TypeVariable)
                and collected_item.name in type_var_tuples
            ):
                return UnpackedType(collected_item)
        return UnpackedType(
            _erase_markers(expression.item, type_var_tuples, broad_type_var_tuples)
        )
    if isinstance(expression, UnionExpression):
        return _union(
            tuple(
                _erase_markers(member, type_var_tuples, broad_type_var_tuples)
                for member in expression.members
            )
        )
    return expression


def _module_contains_literal(module: StubModule) -> bool:
    return any(_declaration_contains_literal(item) for item in module.declarations)


def _declaration_contains_literal(declaration: Declaration) -> bool:
    if isinstance(declaration, FunctionDeclaration):
        return _function_contains_literal(declaration)
    if isinstance(declaration, TypeAliasDeclaration):
        return _contains_literal(declaration.value)
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


def _contains_literal(expression: TypeExpression) -> bool:
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
    imports: tuple[ImportFrom, ...], required: ImportFrom
) -> tuple[ImportFrom, ...]:
    names_by_module: dict[str, set[str]] = {}
    for item in (*imports, required):
        names_by_module.setdefault(item.module, set()).update(item.names)
    return tuple(
        ImportFrom(module, tuple(sorted(names)))
        for module, names in sorted(names_by_module.items())
    )
