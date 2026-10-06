from dataclasses import dataclass, replace
from itertools import product

from returns.result import Failure, Result, Success

from typeforge.compiler.semantic_adapter import (
    SemanticEnvironment,
    named_type_environment,
)
from typeforge.compiler.specialization._bounds import checker_type_bound
from typeforge.compiler.specialization._captures import (
    capture_tokens,
    replace_captures,
)
from typeforge.compiler.specialization._coverage import (
    map_case_covers_domain,
    map_case_input,
    map_covered_cases,
    map_default_reachable,
    map_input_domain,
    map_output_bound,
)
from typeforge.compiler.specialization._evaluation import instantiate_output
from typeforge.compiler.specialization._models import (
    ArityFrontier,
    LoweringError,
    LoweringErrorCode,
)
from typeforge.compiler.stub_ir import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    CaptureType,
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
    ModuleImport,
    NotPredicate,
    OverloadDeclaration,
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
    VariableDeclaration,
    is_predicate,
    merge_imports,
    rewrite_type_children,
    substitute_type,
    walk_declaration,
    walk_module,
    walk_type,
)
from typeforge.utils.error_handling import safe_result


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
    environment = named_type_environment(
        tuple(
            (
                item.name,
                (
                    *(
                        name
                        for base in item.bases
                        if (name := _base_name(base)) is not None
                    ),
                    *(("typing.Protocol",) if item.is_protocol else ()),
                ),
            )
            for item in module.declarations
            if isinstance(item, ClassDeclaration)
        )
    )
    for declaration in module.declarations:
        if isinstance(declaration, ClassDeclaration):
            class_result = _lower_class(
                declaration,
                frontier,
                on_rewrite=record_rewrite,
                environment=environment,
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

        result = _lower_function(
            declaration, frontier, on_rewrite=record_rewrite, environment=environment
        )
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
    if any(
        isinstance(item, TypeName) and item.name == "Any"
        for item in walk_module(lowered_module)
    ):
        lowered_module = replace(
            lowered_module,
            imports=_add_import(lowered_module.imports, ImportFrom("typing", ("Any",))),
        )

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
    *,
    environment: SemanticEnvironment = (),
) -> Result[tuple[ClassDeclaration, bool], LoweringError]:
    methods: list[FunctionDeclaration | OverloadDeclaration] = []
    has_overloads = False
    for method in declaration.methods:
        if isinstance(method, OverloadDeclaration):
            methods.append(method)
            has_overloads = True
            continue

        lowered = _lower_function(
            method,
            frontier,
            on_rewrite=on_rewrite,
            environment=environment,
            reserved_type_parameters=tuple(
                _type_parameter_name(parameter)
                for parameter in declaration.type_parameters
            ),
        )
        if isinstance(lowered, Failure):
            return lowered

        lowered_method = lowered.unwrap()
        methods.append(lowered_method)
        has_overloads = has_overloads or isinstance(lowered_method, OverloadDeclaration)

    return Success((replace(declaration, methods=tuple(methods)), has_overloads))


def _base_name(base: StubTypeExpression) -> str | None:
    match base:
        case TypeName(name) | TypeApplication(TypeName(name), _):
            return name
        case _:
            return None


def _lower_function(
    declaration: FunctionDeclaration,
    frontier: ArityFrontier,
    on_rewrite: TypeRewriteObserver | None = None,
    *,
    environment: SemanticEnvironment = (),
    reserved_type_parameters: tuple[str, ...] = (),
) -> Result[FunctionDeclaration | OverloadDeclaration, LoweringError]:
    if isinstance(declaration.return_type, MapType):
        return _lower_map_function(
            declaration,
            declaration.return_type,
            on_rewrite=on_rewrite,
            environment=environment,
            reserved_type_parameters=reserved_type_parameters,
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
        not is_predicate(case.test) and len(capture_tokens(case.test)) > 1
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
class PredicateMatch:
    input_type: StubTypeExpression
    result: bool


@safe_result(errors=(LoweringError,))
def _lower_map_function(
    declaration: FunctionDeclaration,
    mapping: MapType,
    on_rewrite: TypeRewriteObserver | None = None,
    *,
    environment: SemanticEnvironment = (),
    reserved_type_parameters: tuple[str, ...] = (),
) -> FunctionDeclaration | OverloadDeclaration:
    if not isinstance(mapping.subject, TypeVariable):
        Failure(
            LoweringError(
                LoweringErrorCode.MISSING_CONTROLLER,
                declaration.name,
                "Map subject must be a type parameter at a callable boundary",
            )
        ).unwrap()

    controller = mapping.subject.name
    if not _function_has_controller(declaration, controller):
        Failure(
            LoweringError(
                LoweringErrorCode.MISSING_CONTROLLER,
                declaration.name,
                f"no parameter is controlled by {controller}",
            )
        ).unwrap()

    seen: set[StubTypeExpression | Predicate] = set()
    for case in mapping.cases:
        if case.test in seen:
            Failure(
                LoweringError(
                    LoweringErrorCode.DUPLICATE_MAP_CASE,
                    declaration.name,
                    "Map branch selectors must be unique at a callable boundary",
                )
            ).unwrap()

        seen.add(case.test)
        if is_predicate(case.test):
            predicate_controller_result = predicate_controller(case.test)
            if (
                isinstance(predicate_controller_result, Failure)
                or predicate_controller_result.unwrap() != controller
                or not predicate_is_supported(case.test, controller)
            ):
                Failure(
                    LoweringError(
                        LoweringErrorCode.UNSUPPORTED_PREDICATE,
                        declaration.name,
                        "Map predicate cases must compare the subject type parameter "
                        "to concrete types at a callable boundary",
                    )
                ).unwrap()

    if mapping.cases and isinstance(mapping.cases[0].test, CaptureType):
        # A whole-subject capture covers every admitted input and retains its
        # existing generic identity, including authored bounds and defaults.
        result = replace(
            declaration,
            return_type=instantiate_output(declaration, mapping, environment).unwrap(),
        )
        if on_rewrite is not None:
            on_rewrite(mapping, result.return_type)

        return result

    if mapping.default is None:
        return _lower_covered_map_function(
            declaration, mapping, controller, on_rewrite, environment
        ).unwrap()

    reachability = map_default_reachable(declaration, mapping, controller, environment)
    if isinstance(reachability, Failure) or reachability.unwrap():
        # Validate reachable output bindings before projecting them to a bound.
        instantiate_output(declaration, mapping.default, environment).unwrap()

    specializations = map_specializations(mapping, controller)
    signatures: list[FunctionDeclaration] = []
    covered_domain = False
    for case in specializations:
        if is_predicate(case.test):
            continue

        patterns = (
            case.test.members
            if isinstance(case.test, UnionExpression) and capture_tokens(case.test)
            else (case.test,)
        )
        for pattern in patterns:
            projected = map_case_input(declaration, controller, pattern, environment)
            if isinstance(projected, Failure):
                # Unknown bound facts retain the original bounded aggregate;
                # they never justify a wider specialized input parameter.
                continue

            input_type = projected.unwrap()
            if input_type is None:
                continue

            signature = _captured_map_signature(
                declaration,
                controller,
                input_type,
                _callable_case_output(
                    declaration,
                    mapping,
                    controller,
                    input_type,
                    environment,
                    on_rewrite,
                ),
                selector=pattern,
                reserved_type_parameters=reserved_type_parameters,
                on_rewrite=on_rewrite,
                environment=environment,
            )
            if signature not in signatures:
                signatures.append(signature)

            coverage = map_case_covers_domain(
                declaration, controller, pattern, environment
            )
            covered_domain |= not isinstance(coverage, Failure) and coverage.unwrap()

    fallback = replace(
        declaration,
        return_type=checker_type_bound(
            _union(
                (*(case.output_type for case in mapping.cases), mapping.default),
                on_rewrite=on_rewrite,
            ),
            on_rewrite=on_rewrite,
        ),
    )
    if on_rewrite is not None:
        for signature in (*signatures, fallback):
            on_rewrite(mapping, signature.return_type)

    if not signatures:
        return fallback

    if covered_domain:
        # A broader aggregate would be an unreachable overload. The specialized
        # signatures already include outputs from every admitted subtype.
        return (
            signatures[0]
            if len(signatures) == 1
            else OverloadDeclaration(tuple(signatures[:-1]), signatures[-1])
        )

    return OverloadDeclaration(tuple(signatures), fallback)


def _callable_case_output(
    declaration: FunctionDeclaration,
    mapping: MapType,
    controller: str,
    pattern: StubTypeExpression,
    environment: SemanticEnvironment,
    on_rewrite: TypeRewriteObserver | None,
) -> StubTypeExpression:
    if capture_tokens(mapping):
        return mapping

    match pattern:
        case (
            LiteralType()
            | TypeName("bool" | "None" | "NoneType" | "Never")
            | TypeApplication(TypeName("Literal" | "typing.Literal"), _)
        ):
            # Closed native domains preserve the subject for shared evaluation.
            return mapping
        case _:
            # Ordinary native parameters also admit compatible subtype subjects.
            return map_output_bound(
                declaration,
                mapping,
                controller,
                pattern,
                pattern,
                environment,
                on_rewrite=on_rewrite,
            ).unwrap()


def _captured_map_signature(
    declaration: FunctionDeclaration,
    controller: str,
    pattern: StubTypeExpression,
    output: StubTypeExpression,
    on_rewrite: TypeRewriteObserver | None = None,
    *,
    environment: SemanticEnvironment = (),
    selector: StubTypeExpression | None = None,
    reserved_type_parameters: tuple[str, ...] = (),
) -> FunctionDeclaration:
    source_pattern = pattern if selector is None else selector
    tokens = sorted(
        capture_tokens(pattern),
        key=lambda token: (token.symbol.scope, token.symbol.name),
    )
    reserved = (
        *declaration.type_parameters,
        *reserved_type_parameters,
        *(
            item.name
            for item in walk_declaration(declaration)
            if isinstance(item, TypeVariable | TypeName)
        ),
        *(item.name for item in walk_type(pattern) if isinstance(item, TypeName)),
        *(item.name for item in walk_type(output) if isinstance(item, TypeName)),
    )
    names = _fresh_type_parameter_names(controller, len(tokens), reserved)
    bindings = {
        token: TypeVariable(name) for token, name in zip(tokens, names, strict=True)
    }
    input_type = replace_captures(pattern, bindings, on_rewrite=on_rewrite)
    output_type = (
        instantiate_output(
            declaration,
            substitute_type(output, controller, input_type, on_rewrite=on_rewrite),
            environment,
        ).unwrap()
        if isinstance(output, MapType)
        else replace_captures(output, bindings, on_rewrite=on_rewrite)
    )
    if (
        isinstance(output, MapType)
        and capture_tokens(source_pattern)
        and any(
            isinstance(item, TypeApplication | FixedTuple | HomogeneousTuple)
            for item in walk_type(source_pattern)
        )
    ):
        output_type = _native_capture_output_bound(
            output, source_pattern, controller, input_type, output_type, on_rewrite
        )

    signature = _specialized_signature(
        declaration,
        controller,
        input_type,
        output_type,
        on_rewrite=on_rewrite,
    )
    return replace(signature, type_parameters=(*signature.type_parameters, *names))


def _native_capture_output_bound(
    mapping: MapType,
    pattern: StubTypeExpression,
    controller: str,
    input_type: StubTypeExpression,
    selected_output: StubTypeExpression,
    on_rewrite: TypeRewriteObserver | None,
) -> StubTypeExpression:
    # Native generics admit subclasses with different original type identities.
    # They can fail this structural selector and reach another case or default.
    remaining = tuple(
        case.output_type
        for case in mapping.cases
        if case.test != pattern
        and not (
            isinstance(case.test, UnionExpression) and pattern in case.test.members
        )
    )
    if mapping.default is not None:
        remaining += (mapping.default,)

    fallback_bound = checker_type_bound(
        substitute_type(
            _union(remaining, on_rewrite),
            controller,
            input_type,
            on_rewrite=on_rewrite,
        ),
        on_rewrite=on_rewrite,
    )
    return _union((selected_output, fallback_bound), on_rewrite)


@safe_result(errors=(LoweringError,))
def _lower_covered_map_function(
    declaration: FunctionDeclaration,
    mapping: MapType,
    controller: str,
    on_rewrite: TypeRewriteObserver | None,
    environment: SemanticEnvironment,
) -> FunctionDeclaration | OverloadDeclaration:
    domain = map_input_domain(declaration, mapping, controller, environment).unwrap()
    controller_type = TypeVariable(controller)
    original_domain = dict(declaration.type_parameter_domains).get(controller)
    local_parameter = next(
        (
            parameter
            for parameter in declaration.type_parameters
            if _type_parameter_name(parameter) == controller
        ),
        None,
    )
    if (
        original_domain is not None
        and original_domain != domain
        and (
            local_parameter is None or controller in declaration.type_parameter_defaults
        )
    ):
        Failure(
            LoweringError(
                LoweringErrorCode.UNREPRESENTABLE_COVERAGE,
                declaration.name,
                "the existing type parameter cannot be safely restricted; supply "
                "a covered bound, explicit specialization, or fallback",
            )
        ).unwrap()

    controlled_parameters = tuple(
        parameter
        for parameter in declaration.parameters
        if _has_variable(parameter.annotation, controller)
    )
    preserve_generic = (
        original_domain is not None
        or len(controlled_parameters) != 1
        or controlled_parameters[0].annotation != controller_type
        or any(_has_variable(case.output_type, controller) for case in mapping.cases)
    )
    replacement = controller_type if preserve_generic else domain
    output = map_output_bound(
        declaration, mapping, controller, domain, replacement, environment
    ).unwrap()

    if preserve_generic:
        parameters = tuple(
            controller
            if _type_parameter_name(parameter) == controller
            and original_domain != domain
            else parameter
            for parameter in declaration.type_parameters
        )
        domains = tuple(
            (name, bound)
            for name, bound in declaration.type_parameter_domains
            if name != controller
        )
        result = replace(
            declaration,
            return_type=output,
            type_parameters=parameters,
            type_parameter_domains=(*domains, (controller, domain)),
        )
        if on_rewrite is not None:
            on_rewrite(mapping, result.return_type)

        return result

    cases = map_covered_cases(
        declaration, mapping, controller, domain, environment
    ).unwrap()
    signatures = tuple(
        _specialized_signature(
            declaration, controller, case.test, case.output_type, on_rewrite=on_rewrite
        )
        for case in cases
        if not is_predicate(case.test)
    )
    fallback = _specialized_signature(
        declaration, controller, domain, output, on_rewrite=on_rewrite
    )
    if on_rewrite is not None:
        for signature in (*signatures, fallback):
            on_rewrite(mapping, signature.return_type)

    if len(signatures) <= 1:
        return fallback

    if signatures[-1] == fallback:
        signatures = signatures[:-1]

    return OverloadDeclaration(signatures, fallback)


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
        TypeName("Never") if mapping.default is None else mapping.default,
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

    return TypeName("Never") if mapping.default is None else mapping.default


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
        type_parameter_domains=tuple(
            (
                name,
                _substitute(bound, controller, input_type, on_rewrite=on_rewrite),
            )
            for name, bound in declaration.type_parameter_domains
            if name != controller
        ),
        type_parameter_defaults=tuple(
            name for name in declaration.type_parameter_defaults if name != controller
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
        if predicate.left == variable and predicate.right == variable:
            return True

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
    cases: list[_StructuralMapChoice] = []
    for case in map_specializations(mapping, controller):
        if is_predicate(case.test):
            continue

        bindings = {token: generated_type for token in capture_tokens(case.test)}
        cases.append(
            _StructuralMapChoice(
                replace_captures(case.test, bindings, on_rewrite=on_rewrite),
                replace_captures(case.output_type, bindings, on_rewrite=on_rewrite),
                False,
            )
        )

    if mapping.default is None:
        return tuple(cases)

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
        elif isinstance(current, HomogeneousTuple | EachType | CollectType):
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
        TypeApplication | FixedTuple | HomogeneousTuple | UnionExpression,
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
