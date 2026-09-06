from returns.result import Failure

from typeforge.compiler.specialization import (
    map_default_output,
    map_specializations,
    predicate_controller,
    predicate_is_supported,
)
from typeforge.compiler.stub_ir import (
    FunctionDeclaration,
    MapType,
    StubTypeExpression,
    TypeVariable,
    is_predicate,
    substitute_type,
    union_types,
)
from typeforge.compiler.verification.model import Alternative, ReturnContract


def build_return_contract(signature: FunctionDeclaration) -> ReturnContract | None:
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

    alternatives = tuple(
        Alternative(
            index=index,
            input_type=case.test,
            output_type=substitute_type(
                case.output_type,
                controller,
                case.test,
            ),
        )
        for index, case in enumerate(mapping.cases)
        if not is_predicate(case.test)
    )
    alternatives += (
        Alternative(
            index=len(mapping.cases),
            input_type=None,
            output_type=mapping.default,
            is_default=True,
        ),
    )
    return ReturnContract(
        controller_parameter=controller_parameters[0],
        controller_type_parameter=controller,
        mapping=mapping,
        alternatives=alternatives,
    )


def aggregate_output(contract: ReturnContract) -> StubTypeExpression:
    return union_types(tuple(item.output_type for item in contract.alternatives))
