from collections.abc import Iterator

from typeforge.compiler.pipeline._models import (
    AnnotationProjection,
    AuthoredCallable,
    AuthoredParameter,
    AuthoredParameterKind,
    CompilationPlan,
    TypeParameterProjection,
)
from typeforge.compiler.source import FunctionDeclaration as SourceFunction
from typeforge.compiler.source import ParameterKind, enriched_functions
from typeforge.compiler.specialization import checker_type_bound
from typeforge.compiler.stub_ir import (
    EachType,
    FunctionDeclaration,
    MapType,
    OverloadDeclaration,
    StubTypeExpression,
    TypeVariable,
    walk_declaration,
    walk_type,
)

_PARAMETER_KINDS = {
    ParameterKind.POSITIONAL_ONLY: AuthoredParameterKind.POSITIONAL_ONLY,
    ParameterKind.POSITIONAL_OR_KEYWORD: AuthoredParameterKind.POSITIONAL_OR_KEYWORD,
    ParameterKind.VAR_POSITIONAL: AuthoredParameterKind.VAR_POSITIONAL,
    ParameterKind.KEYWORD_ONLY: AuthoredParameterKind.KEYWORD_ONLY,
    ParameterKind.VAR_KEYWORD: AuthoredParameterKind.VAR_KEYWORD,
}


def describe_authored_callables(plan: CompilationPlan) -> tuple[AuthoredCallable, ...]:
    return tuple(
        AuthoredCallable(
            qualified_name=function.qualified_name,
            parameters=tuple(
                AuthoredParameter(
                    name=parameter.name,
                    kind=_PARAMETER_KINDS[parameter.kind],
                    annotation=(
                        parameter.annotation.source
                        if parameter.annotation is not None
                        else None
                    ),
                    has_default=parameter.has_default,
                )
                for parameter in function.parameters
            ),
            return_annotation=(
                function.returns.source if function.returns is not None else None
            ),
        )
        for function in enriched_functions(plan.source)
    )


def describe_type_parameter_projections(
    plan: CompilationPlan,
) -> tuple[TypeParameterProjection, ...]:
    projections: list[TypeParameterProjection] = []
    for source, contract, declaration in _mapped_callables(plan):
        signature = (
            declaration.fallback
            if isinstance(declaration, OverloadDeclaration)
            else declaration
        )
        for controller in _projection_controllers(contract):
            parameter = next(
                (item for item in source.type_parameters if item.name == controller),
                None,
            )
            if parameter is None or parameter.span is None:
                continue

            domain = _projected_domain(contract, signature, controller)
            original = dict(contract.type_parameter_domains).get(controller)
            if domain is not None and domain != original:
                projections.append(
                    TypeParameterProjection(controller, domain, parameter.span)
                )

    return tuple(projections)


def _projection_controllers(contract: FunctionDeclaration) -> tuple[str, ...]:
    match contract.return_type:
        case MapType(subject=TypeVariable(name), default=None):
            return (name,)
        case _:
            return tuple(
                sorted(
                    {
                        item.name
                        for parameter in contract.parameters
                        if isinstance(parameter.annotation, EachType)
                        for item in walk_type(parameter.annotation)
                        if isinstance(item, TypeVariable)
                    }
                )
            )


def describe_callable_annotations(
    plan: CompilationPlan,
) -> tuple[AnnotationProjection, ...]:
    projections: list[AnnotationProjection] = []
    for source, contract, declaration in _mapped_callables(plan):
        signature = (
            declaration.fallback
            if isinstance(declaration, OverloadDeclaration)
            else declaration
        )
        preserved = frozenset(
            item.name
            for item in walk_declaration(contract)
            if isinstance(item, TypeVariable)
        )
        if source.returns is not None:
            projections.append(
                AnnotationProjection(
                    checker_type_bound(
                        signature.return_type, type_parameters=preserved
                    ),
                    source.returns.span,
                )
            )

        each_names = {
            parameter.name
            for parameter in contract.parameters
            if isinstance(parameter.annotation, EachType)
        }
        parameters = {parameter.name: parameter for parameter in signature.parameters}
        for parameter in source.parameters:
            if parameter.name not in each_names or parameter.annotation is None:
                continue

            projected = parameters[parameter.name]
            projections.append(
                AnnotationProjection(
                    checker_type_bound(projected.annotation, type_parameters=preserved),
                    parameter.annotation.span,
                )
            )

    return tuple(projections)


def _mapped_callables(
    plan: CompilationPlan,
) -> Iterator[
    tuple[
        SourceFunction, FunctionDeclaration, FunctionDeclaration | OverloadDeclaration
    ]
]:
    sources = {function.span: function for function in plan.source.functions}
    reusable = {id(element) for element in plan.module.reusable_elements}
    contracts = {
        origin.origin: origin.generated
        for origin in plan.module.origins
        if id(origin.generated) in reusable
        and isinstance(origin.generated, FunctionDeclaration)
        and (
            isinstance(origin.generated.return_type, MapType)
            or any(
                isinstance(parameter.annotation, EachType)
                for parameter in origin.generated.parameters
            )
        )
    }
    for origin in plan.module.origins:
        declaration = origin.generated
        if id(declaration) in reusable or not isinstance(
            declaration, FunctionDeclaration | OverloadDeclaration
        ):
            continue

        source = sources.get(origin.origin)
        contract = contracts.get(origin.origin)
        if source is not None and contract is not None:
            yield source, contract, declaration


def _projected_domain(
    contract: FunctionDeclaration,
    signature: FunctionDeclaration,
    controller: str,
) -> StubTypeExpression | None:
    domain = dict(signature.type_parameter_domains).get(controller)
    if domain is not None:
        return domain

    parameter = next(
        (
            parameter
            for parameter in contract.parameters
            if parameter.annotation == TypeVariable(controller)
        ),
        None,
    )
    if parameter is None:
        return None

    projected = next(
        (
            item.annotation
            for item in signature.parameters
            if item.name == parameter.name
        ),
        None,
    )
    return None if projected == TypeVariable(controller) else projected
