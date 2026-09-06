from typeforge.compiler.pipeline._models import (
    AuthoredCallable,
    AuthoredParameter,
    AuthoredParameterKind,
    CompilationPlan,
)
from typeforge.compiler.source import ParameterKind, enriched_functions

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
