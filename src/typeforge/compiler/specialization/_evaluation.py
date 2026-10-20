"""Instantiate complete callable outputs with the shared semantic evaluator."""

from collections.abc import Callable
from dataclasses import dataclass

from returns.result import Result, Success

from typeforge.compiler.semantic_adapter import (
    COMPILER_TYPE_SYSTEM,
    SemanticEnvironment,
    SemanticLoweringError,
    StaticType,
    lower_stub_expression,
    static_type_expression,
)
from typeforge.compiler.specialization._bounds import checker_type_bound
from typeforge.compiler.specialization._captures import capture_tokens, replace_captures
from typeforge.compiler.specialization._coverage import (
    map_case_covers_domain,
    map_input_domain,
)
from typeforge.compiler.specialization._models import LoweringError, LoweringErrorCode
from typeforge.compiler.specialization._opaque_bounds import (
    CallableCaptureBounds,
)
from typeforge.compiler.stub_ir import (
    CaptureType,
    FunctionDeclaration,
    MapType,
    StubTypeExpression,
    TypeName,
    TypeVariable,
    walk_type,
)
from typeforge.semantics import (
    EvaluationMode,
    Evaluator,
    IndeterminateType,
    MapNoMatch,
    NoMatchDecision,
    ResolvedType,
    SemanticIssue,
    TypeSymbol,
    UnboundCaptureSemanticError,
    UnresolvedType,
)
from typeforge.utils.error_handling import safe_result

_OUTPUT_ERRORS: tuple[
    type[SemanticIssue | SemanticLoweringError | MapNoMatch[StaticType]], ...
] = (SemanticIssue, SemanticLoweringError, MapNoMatch)


def instantiate_output(
    declaration: FunctionDeclaration,
    expression: StubTypeExpression,
    environment: SemanticEnvironment,
) -> Result[StubTypeExpression, LoweringError]:
    instantiate_safely: Callable[
        [FunctionDeclaration, StubTypeExpression, SemanticEnvironment],
        Result[
            StubTypeExpression,
            SemanticIssue | SemanticLoweringError | MapNoMatch[StaticType],
        ],
    ] = safe_result(errors=_OUTPUT_ERRORS)(_instantiate)
    return instantiate_safely(declaration, expression, environment).alt(
        lambda error: _output_error(declaration, error)
    )


def _output_error(
    declaration: FunctionDeclaration,
    error: SemanticIssue | SemanticLoweringError | MapNoMatch[StaticType],
) -> LoweringError:
    match error:
        case UnboundCaptureSemanticError():
            code = LoweringErrorCode.MISSING_CAPTURE
            message = error.message
        case MapNoMatch(subject=UnresolvedType() | IndeterminateType()):
            code = LoweringErrorCode.UNREPRESENTABLE_COVERAGE
            message = (
                "a nested Map cannot prove coverage of an unresolved argument; "
                "supply an inner fallback or explicit specialization"
            )
        case MapNoMatch():
            code = LoweringErrorCode.UNREPRESENTABLE_OUTPUT
            message = "Map has an uncovered selected input"
        case _:
            code = LoweringErrorCode.UNREPRESENTABLE_OUTPUT
            message = error.message

    return LoweringError(code, declaration.name, message)


@dataclass(frozen=True, slots=True)
class _CallableCoveragePolicy:
    declaration: FunctionDeclaration
    expression: StubTypeExpression
    environment: SemanticEnvironment

    def no_match(self, outcome: MapNoMatch[StaticType]) -> NoMatchDecision:
        if _bound_covers_no_match(self, outcome) == Success(True):
            return NoMatchDecision.ACCEPT

        # A possible normal output does not prove every published input covered.
        return NoMatchDecision.REJECT


@safe_result(errors=(SemanticLoweringError, LoweringError))
def _bound_covers_no_match(
    policy: _CallableCoveragePolicy, outcome: MapNoMatch[StaticType]
) -> bool:
    match outcome.subject:
        case UnresolvedType(provenance=TypeSymbol(scope=("callable",), name=name)):
            controller = name
        case _:
            return False

    if outcome.context.mode is not EvaluationMode.SPECULATIVE:
        return False

    if controller not in dict(policy.declaration.type_parameter_domains):
        return False

    parameters = tuple(
        item.name
        for item in walk_type(policy.expression)
        if isinstance(item, TypeVariable)
    )
    bindings = {
        CaptureType(symbol): static_type_expression(
            value.value, never_name="Never", type_parameters=parameters
        )
        for symbol, value in outcome.context.captures
        if isinstance(value, ResolvedType | UnresolvedType)
    }
    for item in walk_type(policy.expression):
        if not isinstance(item, MapType):
            continue

        if (
            lower_stub_expression(item, policy.environment).unwrap()
            != outcome.expression
        ):
            continue

        mapping = replace_captures(item, bindings)
        assert isinstance(mapping, MapType)
        if mapping.subject != TypeVariable(controller):
            return False

        covered = map_input_domain(
            policy.declaration, mapping, controller, policy.environment
        ).unwrap()
        return map_case_covers_domain(
            policy.declaration, controller, covered, policy.environment
        ).unwrap()

    return False


def _instantiate(
    declaration: FunctionDeclaration,
    expression: StubTypeExpression,
    environment: SemanticEnvironment,
) -> StubTypeExpression:
    reserved = {
        item.name
        for item in walk_type(expression)
        if isinstance(item, TypeVariable | TypeName)
    }
    placeholders: list[tuple[TypeSymbol, str]] = []
    for index, token in enumerate(
        sorted(
            capture_tokens(expression),
            key=lambda item: (item.symbol.scope, item.symbol.name),
        ),
        start=1,
    ):
        name = f"_TypeforgeCapture{index}"
        while name in reserved:
            name += "_"

        reserved.add(name)
        placeholders.append((token.symbol, name))

    result = (
        Evaluator(
            COMPILER_TYPE_SYSTEM,
            policy=_CallableCoveragePolicy(declaration, expression, environment),
            capture_bounds=CallableCaptureBounds(tuple(placeholders)),
        )
        .evaluate(lower_stub_expression(expression, environment).unwrap())
        .unwrap()
    )
    match result:
        case ResolvedType(value=output) | UnresolvedType(value=output):
            pass
        case IndeterminateType(possible_output=ResolvedType(value=output)):
            pass
        case _:
            raise SemanticLoweringError("a callable output must evaluate to a type")

    parameters = tuple(
        item.name for item in walk_type(expression) if isinstance(item, TypeVariable)
    )
    emitted = static_type_expression(
        output,
        never_name="Never",
        type_parameters=(*parameters, *(name for _, name in placeholders)),
    )
    return checker_type_bound(emitted, type_parameters=frozenset(parameters))
