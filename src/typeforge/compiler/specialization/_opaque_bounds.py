"""Supply scoped existential bounds for opaque structural capture arguments."""

from dataclasses import dataclass

from typeforge.compiler.semantic_adapter import NamedType, StaticType
from typeforge.semantics import (
    AlternativeTypePattern,
    CaptureBindings,
    CaptureReference,
    ParameterizedTypePattern,
    TypePattern,
    TypeSymbol,
    TypeValue,
    UnresolvedType,
)


@dataclass(frozen=True, slots=True)
class CallableCaptureBounds:
    # Placeholders are erased at emission; they are never native type parameters.
    # Matching retains existing context values and complete alternative bindings.
    parameters: tuple[tuple[TypeSymbol, str], ...]

    def bindings(
        self, pattern: TypePattern[StaticType], captures: CaptureBindings[StaticType]
    ) -> tuple[CaptureBindings[StaticType], ...]:
        return _capture_contexts(pattern, captures, self.parameters)


def _capture_contexts(
    pattern: TypePattern[StaticType],
    captures: CaptureBindings[StaticType],
    parameters: tuple[tuple[TypeSymbol, str], ...],
) -> tuple[CaptureBindings[StaticType], ...]:
    match pattern:
        case CaptureReference(symbol) if symbol not in dict(captures):
            placeholder: TypeValue[StaticType] = UnresolvedType(
                NamedType(dict(parameters)[symbol]), symbol
            )
            return ((*captures, (symbol, placeholder)),)
        case AlternativeTypePattern(members):
            return tuple(
                bindings
                for member in members
                for bindings in _capture_contexts(member, captures, parameters)
            )
        case ParameterizedTypePattern(arguments=arguments):
            contexts: tuple[CaptureBindings[StaticType], ...] = (captures,)
            for argument in arguments:
                contexts = tuple(
                    bindings
                    for context in contexts
                    for bindings in _capture_contexts(argument, context, parameters)
                )

            return contexts
        case _:
            return (captures,)
