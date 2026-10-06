from dataclasses import replace

from returns.result import Failure

from typeforge.compiler.semantic_adapter import SemanticEnvironment
from typeforge.compiler.specialization import (
    instantiate_output,
    map_case_input,
    map_default_output,
    map_default_reachable,
    map_specializations,
    predicate_controller,
    predicate_is_supported,
)
from typeforge.compiler.stub_ir import (
    EqualPredicate,
    FunctionDeclaration,
    MapType,
    StubTypeExpression,
    TypeName,
    TypeVariable,
    is_predicate,
    substitute_type,
    union_types,
)
from typeforge.compiler.verification.model import Alternative, Guard, ReturnContract


def build_return_contract(
    signature: FunctionDeclaration, environment: SemanticEnvironment = ()
) -> ReturnContract | None:
    relationship = signature.return_type
    if not isinstance(relationship, MapType) or not isinstance(
        relationship.subject, TypeVariable
    ):
        return None

    controller = relationship.subject.name
    for case in relationship.cases:
        if not is_predicate(case.test):
            continue

        predicate_controller_result = predicate_controller(case.test)
        if (
            isinstance(predicate_controller_result, Failure)
            or predicate_controller_result.unwrap() != controller
            or not predicate_is_supported(case.test, controller)
        ):
            return None

    mapping = MapType(
        relationship.subject,
        map_specializations(relationship, controller),
        map_default_output(relationship, controller),
    )
    controller_parameters = tuple(
        parameter.name
        for parameter in signature.parameters
        if parameter.annotation == TypeVariable(controller)
    )
    if len(controller_parameters) != 1:
        return None

    alternatives = _bounded_alternatives(
        signature, mapping, relationship, controller, environment
    )
    if alternatives is None:
        return None

    alternatives += (
        Alternative(
            index=len(mapping.cases),
            input_type=None,
            output_type=TypeName("Never")
            if mapping.default is None
            else mapping.default,
            is_default=True,
        ),
    )
    return ReturnContract(
        controller_parameter=controller_parameters[0],
        controller_type_parameter=controller,
        mapping=relationship,
        alternatives=alternatives,
        declaration=signature,
        environment=environment,
    )


def _bounded_alternatives(
    declaration: FunctionDeclaration,
    mapping: MapType,
    original: MapType,
    controller: str,
    environment: SemanticEnvironment,
) -> tuple[Alternative, ...] | None:
    alternatives: list[Alternative] = []
    for index, case in enumerate(mapping.cases):
        if is_predicate(case.test):
            continue

        projected = map_case_input(declaration, controller, case.test, environment)
        if isinstance(projected, Failure):
            return None

        input_type = projected.unwrap()
        if input_type is None:
            continue

        output = substitute_type(case.output_type, controller, input_type)
        if input_type != case.test:
            evaluated = instantiate_output(
                declaration,
                substitute_type(original, controller, input_type),
                environment,
            )
            if isinstance(evaluated, Failure):
                return None

            output = evaluated.unwrap()

        alternatives.append(Alternative(index, input_type, output))

    return tuple(alternatives)


def guard_fallback_is_reachable(guard: Guard, contract: ReturnContract) -> bool:
    domain = union_types(tuple(TypeName(name) for name in guard.type_names))
    declaration = replace(
        contract.declaration,
        type_parameter_domains=((contract.controller_type_parameter, domain),),
    )
    return map_default_reachable(
        declaration,
        contract.mapping,
        contract.controller_type_parameter,
        contract.environment,
    ).value_or(True)


def has_whole_subject_selector(contract: ReturnContract) -> bool:
    return any(isinstance(case.test, EqualPredicate) for case in contract.mapping.cases)


def aggregate_output(contract: ReturnContract) -> StubTypeExpression:
    return union_types(tuple(item.output_type for item in contract.alternatives))
