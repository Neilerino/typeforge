from typeforge._result import Err
from typeforge.compiler.frontend import parse_source
from typeforge.compiler.model import ParameterKind, enriched_functions
from typeforge.diagnostics.model import (
    AuthoredCallable,
    AuthoredParameter,
    AuthoredParameterKind,
)

_PARAMETER_KINDS = {
    ParameterKind.POSITIONAL_ONLY: AuthoredParameterKind.POSITIONAL_ONLY,
    ParameterKind.POSITIONAL_OR_KEYWORD: AuthoredParameterKind.POSITIONAL_OR_KEYWORD,
    ParameterKind.VAR_POSITIONAL: AuthoredParameterKind.VAR_POSITIONAL,
    ParameterKind.KEYWORD_ONLY: AuthoredParameterKind.KEYWORD_ONLY,
    ParameterKind.VAR_KEYWORD: AuthoredParameterKind.VAR_KEYWORD,
}


def collect_authored_callables(source: str) -> tuple[AuthoredCallable, ...]:
    parsed = parse_source(source)
    if isinstance(parsed, Err):
        return ()
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
        for function in enriched_functions(parsed.value)
    )
