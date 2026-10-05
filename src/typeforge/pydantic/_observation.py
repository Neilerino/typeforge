"""Runtime typing reflection and raw-value observations, without Map ordering."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Literal, Never, TypeAliasType, Union, get_args, get_origin

from typeforge import semantics as s
from typeforge.pydantic._policy import InputTestKind
from typeforge.pydantic._type_system import RuntimeType
from typeforge.utils.error_handling import safe_result


@dataclass(frozen=True, slots=True)
class RawInput:
    value: object

    @safe_result(errors=(s.SemanticIssue,))
    def matches(
        self,
        test: s.Expression[RuntimeType] | s.TypePattern[RuntimeType],
        context: s.EvaluationContext[RuntimeType],
    ) -> bool:
        match test:
            case s.InputReference():
                return True

            case s.TypeReference(value=target) | s.ExactTypePattern(value=target):
                return matches_type(target.value, self.value)

            case s.ValueReference():
                bound = context.value
                if isinstance(bound, s.ResolvedType):
                    return matches_type(bound.value.value, self.value)

                raise s.UnboundValueSemanticError("Value requires a field binding")

            case s.CaptureReference(symbol=symbol):
                bound = dict(context.captures).get(symbol)
                if isinstance(bound, s.ResolvedType):
                    return matches_type(bound.value.value, self.value)

                raise s.UnboundCaptureSemanticError(
                    f"capture {symbol.name!r} requires a resolved binding"
                )

            case _:
                raise s.UnsupportedExpressionSemanticError(
                    "unsupported Input case test"
                )


def input_test_kinds(
    test: s.Expression[RuntimeType] | s.TypePattern[RuntimeType],
    context: s.EvaluationContext[RuntimeType],
) -> Iterator[InputTestKind]:
    match test:
        case s.ParameterizedTypePattern() | s.ParameterizedTypeTemplate():
            yield InputTestKind.PARAMETERIZED

        case s.TypeReference(value=target) | s.ExactTypePattern(value=target):
            yield from _type_kinds(target.value)

        case s.AnnotatedExpression(value=inner):
            yield from input_test_kinds(inner, context)

        case s.UnionExpression(members=members):
            for member in members:
                yield from input_test_kinds(member, context)

        case s.ValueReference():
            bound = context.value
            if isinstance(bound, s.ResolvedType):
                yield from _type_kinds(bound.value.value)
            else:
                yield InputTestKind.UNBOUND_VALUE

        case s.InputReference():
            yield InputTestKind.INPUT

        case s.CaptureReference(symbol=symbol):
            bound = dict(context.captures).get(symbol)
            if isinstance(bound, s.ResolvedType):
                yield from _type_kinds(bound.value.value)
            else:
                yield InputTestKind.UNBOUND_CAPTURE

        case (
            s.EqualExpression()
            | s.AssignableExpression()
            | s.AllExpression()
            | s.AnyExpression()
            | s.NotExpression()
        ):
            # Reached predicates, including their operands, belong to evaluation.
            yield InputTestKind.PREDICATE

        case _:
            yield InputTestKind.UNSUPPORTED


def _type_kinds(
    target: object, seen: tuple[TypeAliasType, ...] = ()
) -> Iterator[InputTestKind]:
    origin = get_origin(target)
    if origin is Annotated:
        yield from _type_kinds(get_args(target)[0], seen)

    elif origin is Union:
        for member in get_args(target):
            yield from _type_kinds(member, seen)

    elif isinstance(target, TypeAliasType) and target not in seen:
        yield from _type_kinds(target.__value__, (*seen, target))

    elif origin is not None and origin is not Literal:
        yield InputTestKind.PARAMETERIZED

    elif isinstance(target, type) or origin is Literal or target is Never:
        yield InputTestKind.TYPE

    else:
        yield InputTestKind.UNSUPPORTED


def matches_type(target: object, value: object) -> bool:
    origin = get_origin(target)
    if origin is Annotated:
        return matches_type(get_args(target)[0], value)

    if origin is Union:
        return any(matches_type(member, value) for member in get_args(target))

    if origin is Literal:
        return any(
            type(value) is type(item) and value == item for item in get_args(target)
        )

    if isinstance(target, TypeAliasType):
        return matches_type(target.__value__, value)

    return isinstance(target, type) and type(value) is target
