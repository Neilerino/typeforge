from typeforge.compiler.pipeline._models import (
    AuthoredCallable,
    AuthoredParameter,
    AuthoredParameterKind,
    CompilationPlan,
    TypeParameterProjection,
)
from typeforge.compiler.source import ParameterKind, enriched_functions
from typeforge.compiler.stub_ir import (
    FunctionDeclaration,
    MapType,
    OverloadDeclaration,
    StubTypeExpression,
    TypeVariable,
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
    sources = {function.span: function for function in plan.source.functions}
    reusable = {id(element) for element in plan.module.reusable_elements}
    contracts = {
        origin.origin: origin.generated
        for origin in plan.module.origins
        if id(origin.generated) in reusable
        and isinstance(origin.generated, FunctionDeclaration)
    }
    projections: list[TypeParameterProjection] = []
    for origin in plan.module.origins:
        declaration = origin.generated
        if id(declaration) in reusable or not isinstance(
            declaration, FunctionDeclaration | OverloadDeclaration
        ):
            continue

        source = sources.get(origin.origin)
        contract = contracts.get(origin.origin)
        if source is None or contract is None:
            continue

        mapping = contract.return_type
        if (
            not isinstance(mapping, MapType)
            or mapping.default is not None
            or (not isinstance(mapping.subject, TypeVariable))
        ):
            continue

        controller = mapping.subject.name
        parameter = next(
            (item for item in source.type_parameters if item.name == controller), None
        )
        if parameter is None or parameter.span is None:
            continue

        signature = (
            declaration.fallback
            if isinstance(declaration, OverloadDeclaration)
            else declaration
        )
        domain = _projected_domain(contract, signature, controller)
        original = dict(contract.type_parameter_domains).get(controller)
        if domain is not None and domain != original:
            projections.append(
                TypeParameterProjection(controller, domain, parameter.span)
            )

    return tuple(projections)


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

    return next(
        (
            item.annotation
            for item in signature.parameters
            if item.name == parameter.name
        ),
        None,
    )
