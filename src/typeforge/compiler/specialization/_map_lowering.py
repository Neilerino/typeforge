"""Scalar callable projection over native Map input domains."""

from dataclasses import replace

from returns.result import Failure

from typeforge.compiler.semantic_adapter import SemanticEnvironment
from typeforge.compiler.specialization._bounds import checker_type_bound
from typeforge.compiler.specialization._captures import capture_tokens, replace_captures
from typeforge.compiler.specialization._coverage import (
    map_case_covers_domain,
    map_case_input,
    map_covered_cases,
    map_default_reachable,
    map_input_domain,
    map_output_bound,
)
from typeforge.compiler.specialization._evaluation import instantiate_output
from typeforge.compiler.specialization._expressions import (
    fresh_type_parameter_names,
    has_variable,
    substitute_scalar,
    type_parameter_name,
    union_types,
)
from typeforge.compiler.specialization._models import LoweringError, LoweringErrorCode
from typeforge.compiler.specialization._predicates import (
    map_specializations,
    predicate_controller,
    predicate_is_supported,
)
from typeforge.compiler.stub_ir import (
    CaptureType,
    FixedTuple,
    FunctionDeclaration,
    HomogeneousTuple,
    LiteralType,
    MapType,
    OverloadDeclaration,
    Predicate,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeRewriteObserver,
    TypeVariable,
    UnionExpression,
    is_predicate,
    substitute_type,
    walk_declaration,
    walk_type,
)
from typeforge.utils.error_handling import safe_result


@safe_result(errors=(LoweringError,))
def lower_map_function(
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
        )

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
            union_types(
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
    names = fresh_type_parameter_names(controller, len(tokens), reserved)
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
            union_types(remaining, on_rewrite),
            controller,
            input_type,
            on_rewrite=on_rewrite,
        ),
        on_rewrite=on_rewrite,
    )
    return union_types((selected_output, fallback_bound), on_rewrite)


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
            if type_parameter_name(parameter) == controller
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
        if has_variable(parameter.annotation, controller)
    )
    preserve_generic = (
        original_domain is not None
        or len(controlled_parameters) != 1
        or controlled_parameters[0].annotation != controller_type
        or any(has_variable(case.output_type, controller) for case in mapping.cases)
    )
    replacement = controller_type if preserve_generic else domain
    output = map_output_bound(
        declaration, mapping, controller, domain, replacement, environment
    ).unwrap()

    if preserve_generic:
        parameters = tuple(
            controller
            if type_parameter_name(parameter) == controller
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
                annotation=substitute_scalar(
                    parameter.annotation, controller, input_type, on_rewrite=on_rewrite
                ),
            )
            for parameter in declaration.parameters
        ),
        return_type=substitute_scalar(
            return_type, controller, input_type, on_rewrite=on_rewrite
        ),
        type_parameters=tuple(
            item
            for item in declaration.type_parameters
            if type_parameter_name(item) != controller
        ),
        type_parameter_domains=tuple(
            (
                name,
                substitute_scalar(bound, controller, input_type, on_rewrite=on_rewrite),
            )
            for name, bound in declaration.type_parameter_domains
            if name != controller
        ),
        type_parameter_defaults=tuple(
            name for name in declaration.type_parameter_defaults if name != controller
        ),
    )


def _function_has_controller(declaration: FunctionDeclaration, controller: str) -> bool:
    return any(
        has_variable(parameter.annotation, controller)
        for parameter in declaration.parameters
    )
