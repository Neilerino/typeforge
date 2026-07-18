from typeforge._result import Err, Ok, Result
from typeforge.compiler.lowering import (
    AllPredicate,
    AnyPredicate,
    IfType,
    MapCase,
    MapType,
    NotPredicate,
    Predicate,
    TypeExpression,
    TypeName,
    TypeVariable,
    UnionExpression,
    predicate_controller,
    predicate_is_supported,
    predicate_matches,
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
    if isinstance(adapted, Err):
        return adapted
    expanded = expand_function_map_aliases(adapted.value, aliases)
    relationship = expanded.return_type
    mapping = (
        relationship
        if isinstance(relationship, MapType)
        else _conditional_mapping(relationship)
        if isinstance(relationship, IfType)
        else None
    )
    if mapping is None or not isinstance(mapping.subject, TypeVariable):
        return Ok(None)
    controller = mapping.subject.name
    controller_parameters = tuple(
        parameter.name
        for parameter in expanded.parameters
        if parameter.annotation == TypeVariable(controller)
    )
    if len(controller_parameters) != 1:
        return Ok(None)
    alternatives = tuple(
        Alternative(
            index=index,
            input_type=case.input_type,
            output_type=substitute_type(
                case.output_type,
                controller,
                case.input_type,
            ),
        )
        for index, case in enumerate(mapping.cases)
    )
    alternatives += (
        Alternative(
            index=len(mapping.cases),
            input_type=None,
            output_type=mapping.default,
            is_default=True,
        ),
    )
    return Ok(
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


def _conditional_mapping(conditional: IfType) -> MapType | None:
    controller = predicate_controller(conditional.condition)
    if isinstance(controller, Err) or not predicate_is_supported(
        conditional.condition, controller.value
    ):
        return None
    matches = predicate_matches(conditional.condition, controller.value)
    cases = tuple(
        MapCase(
            match.input_type,
            conditional.when_true if match.result else conditional.when_false,
        )
        for match in matches
    )
    default = (
        conditional.when_true
        if _predicate_default(conditional.condition)
        else conditional.when_false
    )
    return MapType(TypeVariable(controller.value), cases, default)


def _predicate_default(predicate: Predicate) -> bool:
    if isinstance(predicate, NotPredicate):
        return not _predicate_default(predicate.predicate)
    if isinstance(predicate, AllPredicate):
        return all(_predicate_default(item) for item in predicate.predicates)
    if isinstance(predicate, AnyPredicate):
        return any(_predicate_default(item) for item in predicate.predicates)
    return False


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
