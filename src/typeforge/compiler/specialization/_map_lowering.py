"""Scalar callable projection over native Map input domains."""

from dataclasses import replace

from returns.result import Failure, Result, Success

from typeforge.compiler.semantic_adapter import SemanticEnvironment
from typeforge.compiler.specialization._coverage import (
    map_covered_cases,
    map_input_domain,
    map_output_bound,
)
from typeforge.compiler.specialization._expressions import (
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
    FunctionDeclaration,
    MapType,
    OverloadDeclaration,
    Predicate,
    StubTypeExpression,
    TypeRewriteObserver,
    TypeVariable,
    is_predicate,
)
from typeforge.utils.error_handling import safe_result


def lower_map_function(
    declaration: FunctionDeclaration,
    mapping: MapType,
    on_rewrite: TypeRewriteObserver | None = None,
    *,
    environment: SemanticEnvironment = (),
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
                    "Map branch selectors must be unique at a callable boundary",
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

    if mapping.default is None:
        return _lower_covered_map_function(
            declaration, mapping, controller, on_rewrite, environment
        )

    specializations = map_specializations(mapping, controller)
    signatures = tuple(
        _specialized_signature(
            declaration,
            controller,
            case.test,
            substitute_scalar(
                case.output_type, controller, case.test, on_rewrite=on_rewrite
            ),
            on_rewrite=on_rewrite,
        )
        for case in specializations
        if not is_predicate(case.test)
    )
    fallback = replace(
        declaration,
        return_type=union_types(
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
