from returns.result import Failure, Result, Success

from typeforge.compiler.lowering import (
    MapType,
    TypeExpression,
    TypeName,
    TypeVariable,
    UnionExpression,
    is_predicate,
    map_default_output,
    map_specializations,
    predicate_controller,
    predicate_is_supported,
)
from typeforge.compiler.model import FunctionDeclaration as SourceFunction
from typeforge.compiler.pipeline import (
    AdaptationError,
    SemanticRelationshipAlias,
    adapt_function,
    expand_function_map_aliases,
    substitute_type,
)
from typeforge.verification.model import Alternative, ReturnContract


def build_return_contract(
    function: SourceFunction,
    aliases: tuple[SemanticRelationshipAlias, ...],
    enclosing_type_parameters: tuple[str, ...] = (),
) -> Result[ReturnContract | None, AdaptationError]:
    adapted = adapt_function(function, enclosing_type_parameters)
    if isinstance(adapted, Failure):
        return adapted
    expanded = expand_function_map_aliases(adapted.unwrap(), aliases)
    relationship = expanded.return_type
    if not isinstance(relationship, MapType) or not isinstance(
        relationship.subject, TypeVariable
    ):
        return Success(None)
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
            return Success(None)
    mapping = MapType(
        relationship.subject,
        map_specializations(relationship, controller),
        map_default_output(relationship, controller),
    )
    controller_parameters = tuple(
        parameter.name
        for parameter in expanded.parameters
        if parameter.annotation == TypeVariable(controller)
    )
    if len(controller_parameters) != 1:
        return Success(None)
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
    return Success(
        ReturnContract(
            qualified_name=function.qualified_name,
            return_annotation=(
                function.returns.source if function.returns is not None else "Any"
            ),
            controller_parameter=controller_parameters[0],
            controller_type_parameter=controller,
            mapping=mapping,
            alternatives=alternatives,
        )
    )


def aggregate_output(contract: ReturnContract) -> TypeExpression:
    return union_types(tuple(item.output_type for item in contract.alternatives))


def union_types(expressions: tuple[TypeExpression, ...]) -> TypeExpression:
    flattened: list[TypeExpression] = []
    for expression in expressions:
        members = (
            expression.members
            if isinstance(expression, UnionExpression)
            else (expression,)
        )
        for member in members:
            if member not in flattened:
                flattened.append(member)
    if not flattened:
        return TypeName("Never")
    if len(flattened) == 1:
        return flattened[0]
    return UnionExpression(tuple(flattened))
