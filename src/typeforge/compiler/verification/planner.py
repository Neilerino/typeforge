import ast
from dataclasses import dataclass

from typeforge.compiler.emission import emit_type_expression
from typeforge.compiler.semantic_adapter import (
    NamedType,
    SemanticEnvironment,
    stub_type_environment,
)
from typeforge.compiler.source import (
    FunctionDeclaration as SourceFunction,
)
from typeforge.compiler.source import (
    ParsedSource,
    SourceModule,
    SourcePosition,
)
from typeforge.compiler.stub_ir import (
    FunctionDeclaration,
    StubModule,
    StubTypeExpression,
    TypeName,
    UnionExpression,
)
from typeforge.compiler.verification.contracts import (
    aggregate_output,
    build_return_contract,
    guard_fallback_is_reachable,
    has_whole_subject_selector,
)
from typeforge.compiler.verification.guards import recognize_guard, recognize_pattern
from typeforge.compiler.verification.model import (
    Alternative,
    FlowState,
    Guard,
    GuardMode,
    ImplicitReturnSite,
    ReturnContract,
    ReturnObligation,
    VerificationPlan,
)


@dataclass(frozen=True, slots=True)
class _FlowResult:
    continuing: tuple[FlowState, ...]
    obligations: tuple[ReturnObligation, ...]


@dataclass(frozen=True, slots=True)
class _PlanningContext:
    source: SourceModule
    function: SourceFunction
    contract: ReturnContract
    never_functions: frozenset[str]


def analyze_implementations(
    parsed: ParsedSource, module: StubModule
) -> VerificationPlan:
    source = parsed.source
    environment = stub_type_environment(module)
    nodes = {
        SourcePosition(node.lineno, node.col_offset): node
        for node in ast.walk(parsed.tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    roots = {
        id(element): element
        for element in module.reusable_elements
        if isinstance(element, FunctionDeclaration)
    }
    signatures = {
        origin.origin: roots[id(origin.generated)]
        for origin in module.origins
        if id(origin.generated) in roots
    }
    never_functions = frozenset(
        function.name
        for function in source.functions
        if function.returns is not None
        and function.returns.source in {"Never", "NoReturn", "typing.Never"}
    )
    obligations: list[ReturnObligation] = []
    for function in source.functions:
        node = nodes.get(function.span.start)
        if (
            node is None
            or _is_generator(node)
            or _is_declaration_only(node)
            or _is_overload(function.decorators)
        ):
            continue

        signature = signatures.get(function.span)
        contract = (
            build_return_contract(signature, environment)
            if signature is not None
            else None
        )
        if contract is None:
            continue

        initial = FlowState(tuple(item.index for item in contract.alternatives))
        context = _PlanningContext(source, function, contract, never_functions)
        analyzed = _analyze_statements(node.body, (initial,), context)
        obligations.extend(analyzed.obligations)
        obligations.extend(_fallthrough_obligations(analyzed.continuing, context))

    return VerificationPlan(tuple(obligations))


def _analyze_statements(
    statements: list[ast.stmt],
    states: tuple[FlowState, ...],
    context: _PlanningContext,
) -> _FlowResult:
    continuing = states
    obligations: list[ReturnObligation] = []
    for statement in statements:
        if not continuing:
            break

        result = _analyze_statement(statement, _join_states(continuing), context)
        continuing = result.continuing
        obligations.extend(result.obligations)

    return _FlowResult(continuing, tuple(obligations))


def _analyze_statement(
    statement: ast.stmt,
    states: tuple[FlowState, ...],
    context: _PlanningContext,
) -> _FlowResult:
    if isinstance(statement, ast.Return):
        state = _merged_state(states)
        return _FlowResult((), (_return_obligation(statement, state, context),))

    if isinstance(statement, ast.Raise | ast.Break | ast.Continue):
        return _FlowResult((), ())

    if isinstance(statement, ast.Expr) and _is_never_call(
        statement.value, context.never_functions
    ):
        return _FlowResult((), ())

    if isinstance(statement, ast.If):
        return _analyze_if(statement, states, context)

    if isinstance(statement, ast.Assert):
        positive, _ = _partition_expression(
            statement.test, _merged_state(states), context.contract
        )
        return _FlowResult((positive,), ())

    if isinstance(statement, ast.Match):
        return _analyze_match(statement, states, context)

    if isinstance(statement, ast.For | ast.AsyncFor):
        entered = tuple(
            _invalidate_if_bound(state, statement.target, context.contract)
            for state in states
        )
        body = _analyze_statements(statement.body, entered, context)
        otherwise = _analyze_statements(statement.orelse, states, context)
        return _FlowResult(
            _join_states((*states, *otherwise.continuing)),
            (*body.obligations, *otherwise.obligations),
        )

    if isinstance(statement, ast.While):
        positive, _ = _partition_expression(
            statement.test, _merged_state(states), context.contract
        )
        body = _analyze_statements(statement.body, (positive,), context)
        otherwise = _analyze_statements(statement.orelse, states, context)
        return _FlowResult(
            _join_states((*states, *otherwise.continuing)),
            (*body.obligations, *otherwise.obligations),
        )

    if isinstance(statement, ast.With | ast.AsyncWith):
        current = states
        for item in statement.items:
            if item.optional_vars is not None:
                current = tuple(
                    _invalidate_if_bound(state, item.optional_vars, context.contract)
                    for state in current
                )

        return _analyze_statements(statement.body, current, context)

    if isinstance(statement, ast.Try | ast.TryStar):
        return _analyze_try(statement, states, context)

    if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return _FlowResult(
            tuple(
                _invalidate_symbol(state, statement.name, context.contract)
                for state in states
            ),
            (),
        )

    if isinstance(statement, ast.Assign):
        return _FlowResult(
            tuple(
                _invalidate_for_targets(state, statement.targets, context.contract)
                for state in states
            ),
            (),
        )

    if isinstance(statement, ast.AnnAssign | ast.AugAssign):
        return _FlowResult(
            tuple(
                _invalidate_if_bound(state, statement.target, context.contract)
                for state in states
            ),
            (),
        )

    if isinstance(statement, ast.Delete):
        return _FlowResult(
            tuple(
                _invalidate_for_targets(state, statement.targets, context.contract)
                for state in states
            ),
            (),
        )

    return _FlowResult(states, ())


def _analyze_if(
    statement: ast.If,
    states: tuple[FlowState, ...],
    context: _PlanningContext,
) -> _FlowResult:
    positive, negative = _partition_expression(
        statement.test, _merged_state(states), context.contract
    )
    body = _analyze_statements(statement.body, (positive,), context)
    otherwise = _analyze_statements(statement.orelse, (negative,), context)
    return _FlowResult(
        _join_states((*body.continuing, *otherwise.continuing)),
        (*body.obligations, *otherwise.obligations),
    )


def _analyze_match(
    statement: ast.Match,
    states: tuple[FlowState, ...],
    context: _PlanningContext,
) -> _FlowResult:
    if not (
        isinstance(statement.subject, ast.Name)
        and statement.subject.id == context.contract.controller_parameter
        and _merged_state(states).controller_valid
    ):
        unmatched_obligations = tuple(
            obligation
            for case in statement.cases
            for obligation in _analyze_statements(
                case.body, states, context
            ).obligations
        )
        return _FlowResult(states, unmatched_obligations)

    remaining = _merged_state(states)
    continuing: list[FlowState] = []
    obligations: list[ReturnObligation] = []
    for case in statement.cases:
        guard = recognize_pattern(case.pattern, context.contract.controller_parameter)
        if guard is None:
            if isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None:
                selected = remaining
                remaining = FlowState((), True, remaining.controller_valid)
            else:
                selected = FlowState(
                    remaining.alternatives,
                    False,
                    remaining.controller_valid,
                )
        else:
            selected, remaining = _partition_guard(guard, remaining, context.contract)

        if case.guard is not None:
            selected, rejected = _partition_expression(
                case.guard, selected, context.contract
            )
            remaining = _union_states((remaining, rejected))

        result = _analyze_statements(case.body, (selected,), context)
        continuing.extend(result.continuing)
        obligations.extend(result.obligations)

    if remaining.alternatives:
        continuing.append(remaining)

    return _FlowResult(_join_states(tuple(continuing)), tuple(obligations))


def _analyze_try(
    statement: ast.Try | ast.TryStar,
    states: tuple[FlowState, ...],
    context: _PlanningContext,
) -> _FlowResult:
    body = _analyze_statements(statement.body, states, context)
    handlers = tuple(
        _analyze_statements(handler.body, states, context)
        for handler in statement.handlers
    )
    otherwise = _analyze_statements(statement.orelse, body.continuing, context)
    pre_final = _join_states(
        (
            *otherwise.continuing,
            *(state for item in handlers for state in item.continuing),
        )
    )
    final = _analyze_statements(statement.finalbody, pre_final, context)
    return _FlowResult(
        final.continuing,
        (
            *body.obligations,
            *(obligation for item in handlers for obligation in item.obligations),
            *otherwise.obligations,
            *final.obligations,
        ),
    )


def _partition_expression(
    expression: ast.expr,
    state: FlowState,
    contract: ReturnContract,
) -> tuple[FlowState, FlowState]:
    if isinstance(expression, ast.BoolOp) and expression.values:
        if isinstance(expression.op, ast.And):
            positive = state
            negative_parts: list[FlowState] = []
            for item in expression.values:
                item_positive, item_negative = _partition_expression(
                    item, positive, contract
                )
                negative_parts.append(item_negative)
                positive = item_positive

            return positive, _union_states(tuple(negative_parts))

        negative = state
        positive_parts: list[FlowState] = []
        for item in expression.values:
            item_positive, item_negative = _partition_expression(
                item, negative, contract
            )
            positive_parts.append(item_positive)
            negative = item_negative

        return _union_states(tuple(positive_parts)), negative

    recognized = recognize_guard(expression, contract.controller_parameter)
    if recognized is None or not state.controller_valid:
        return state, state

    guard, positive_polarity = recognized
    matched, unmatched = _partition_guard(guard, state, contract)
    return (matched, unmatched) if positive_polarity else (unmatched, matched)


def _partition_guard(
    guard: Guard,
    state: FlowState,
    contract: ReturnContract,
) -> tuple[FlowState, FlowState]:
    available = tuple(
        item for item in contract.alternatives if item.index in state.alternatives
    )
    rendered = {item.index: _runtime_input_names(item.input_type) for item in available}
    guard_types = tuple(
        normalized
        for item in guard.type_names
        if (normalized := _normalize_type(item)) is not None
    )
    explicit_matches = {
        item.index
        for item in available
        if not item.is_default
        and any(name in guard_types for name in rendered[item.index])
    }
    unresolved = {
        item.index
        for item in available
        if not item.is_default and None in rendered[item.index]
    }
    if guard.mode is GuardMode.INSTANCE:
        explicit_matches.update(
            item.index
            for item in available
            if not item.is_default
            and any(
                _known_runtime_subclass(name, guard_types, contract.environment)
                for name in rendered[item.index]
            )
        )
        default = next((item for item in available if item.is_default), None)
        positive_indices = explicit_matches | unresolved
        if (
            default is not None
            and _render_output(default) != "Never"
            and guard_fallback_is_reachable(guard, contract)
        ):
            positive_indices.add(default.index)

        fully_matched = {
            item.index
            for item in available
            if not item.is_default
            and all(
                name in guard_types
                or _known_runtime_subclass(name, guard_types, contract.environment)
                for name in rendered[item.index]
            )
        }
    else:
        default = next((item for item in available if item.is_default), None)
        positive_indices = explicit_matches | unresolved
        if default is not None and (
            not positive_indices
            or (
                has_whole_subject_selector(contract)
                and guard_fallback_is_reachable(guard, contract)
            )
        ):
            positive_indices.add(default.index)

        fully_matched = {
            item.index
            for item in available
            if not item.is_default
            and all(name in guard_types for name in rendered[item.index])
        }

    negative_indices = unresolved | {
        item.index for item in available if item.index not in fully_matched
    }
    return (
        FlowState(
            tuple(sorted(positive_indices)),
            not unresolved,
            state.controller_valid,
            narrowed_inputs=tuple(TypeName(name) for name in guard.type_names),
        ),
        FlowState(
            tuple(sorted(negative_indices)),
            not unresolved,
            state.controller_valid,
        ),
    )


def _return_obligation(
    statement: ast.Return,
    state: FlowState,
    context: _PlanningContext,
) -> ReturnObligation:
    position = SourcePosition(statement.lineno, statement.col_offset)
    site = next(
        site for site in context.source.return_sites if site.statement.start == position
    )
    return ReturnObligation(
        function=context.function,
        contract=context.contract,
        site=site,
        expected_types=_expected_types(state, context.contract),
        narrowed_inputs=state.narrowed_inputs
        or tuple(
            item.input_type
            for item in context.contract.alternatives
            if item.index in state.alternatives
            and not item.is_default
            and item.input_type is not None
        ),
    )


def _fallthrough_obligations(
    states: tuple[FlowState, ...],
    context: _PlanningContext,
) -> tuple[ReturnObligation, ...]:
    if not states or context.function.body_span is None:
        return ()

    return (
        ReturnObligation(
            function=context.function,
            contract=context.contract,
            site=ImplicitReturnSite(context.function.body_span),
            expected_types=_expected_types(_merged_state(states), context.contract),
            narrowed_inputs=(),
        ),
    )


def _expected_types(
    state: FlowState, contract: ReturnContract
) -> tuple[StubTypeExpression, ...]:
    if not state.refined or not state.controller_valid:
        return (aggregate_output(contract),)

    values = tuple(
        item.output_type
        for item in contract.alternatives
        if item.index in state.alternatives
    )
    deduplicated: list[StubTypeExpression] = []
    for value in values:
        if value not in deduplicated:
            deduplicated.append(value)

    return tuple(deduplicated)


def _join_states(states: tuple[FlowState, ...]) -> tuple[FlowState, ...]:
    if not states:
        return ()

    unique: list[FlowState] = []
    for state in states:
        if state.alternatives and state not in unique:
            unique.append(state)

    return tuple(unique)


def _merged_state(states: tuple[FlowState, ...]) -> FlowState:
    if not states:
        return FlowState(())

    if len(states) == 1:
        return states[0]

    return FlowState(
        alternatives=tuple(
            sorted({item for state in states for item in state.alternatives})
        ),
        refined=False,
        controller_valid=all(state.controller_valid for state in states),
    )


def _union_states(states: tuple[FlowState, ...]) -> FlowState:
    reachable = tuple(state for state in states if state.alternatives)
    if not reachable:
        return FlowState(())

    return FlowState(
        alternatives=tuple(
            sorted({item for state in reachable for item in state.alternatives})
        ),
        refined=all(state.refined for state in reachable),
        controller_valid=all(state.controller_valid for state in reachable),
        narrowed_inputs=tuple(
            dict.fromkeys(item for state in reachable for item in state.narrowed_inputs)
        ),
    )


def _invalidate_for_targets(
    state: FlowState,
    targets: list[ast.expr],
    contract: ReturnContract,
) -> FlowState:
    result = state
    for target in targets:
        result = _invalidate_if_bound(result, target, contract)

    return result


def _invalidate_if_bound(
    state: FlowState,
    target: ast.expr,
    contract: ReturnContract,
) -> FlowState:
    if any(
        isinstance(item, ast.Name) and item.id == contract.controller_parameter
        for item in ast.walk(target)
    ):
        return FlowState(state.alternatives, False, False)

    return state


def _invalidate_symbol(
    state: FlowState,
    symbol: str,
    contract: ReturnContract,
) -> FlowState:
    return (
        FlowState(state.alternatives, False, False)
        if symbol == contract.controller_parameter
        else state
    )


def _runtime_input_names(
    expression: StubTypeExpression | None,
) -> tuple[str | None, ...]:
    match expression:
        case None:
            return ()
        case UnionExpression(members):
            return tuple(
                name for item in members for name in _runtime_input_names(item)
            )
        case _:
            rendered = emit_type_expression(expression).value_or(None)
            return (_normalize_type(rendered),)


def _render_output(alternative: Alternative) -> str | None:
    return emit_type_expression(alternative.output_type).value_or(None)


def _known_runtime_subclass(
    candidate: str | None, parents: tuple[str, ...], environment: SemanticEnvironment
) -> bool:
    if candidate == "bool" and "int" in parents:
        return True

    known = dict(environment).get(candidate or "")
    return isinstance(known, NamedType) and any(
        parent in known.bases for parent in parents
    )


def _normalize_type(value: str | None) -> str | None:
    if value is None:
        return None

    try:
        return ast.unparse(ast.parse(value, mode="eval").body)
    except SyntaxError:
        return value


def _is_generator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    class YieldFinder(ast.NodeVisitor):
        def __init__(self) -> None:
            self.found = False

        def visit_Yield(self, node: ast.Yield) -> None:
            del node
            self.found = True

        def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
            del node
            self.found = True

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            del node

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            del node

        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

    finder = YieldFinder()
    for statement in node.body:
        finder.visit(statement)

    return finder.found


def _is_declaration_only(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return len(node.body) == 1 and (
        isinstance(node.body[0], ast.Pass)
        or (
            isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and node.body[0].value.value is Ellipsis
        )
    )


def _is_overload(decorators: tuple[str, ...]) -> bool:
    return any(item == "overload" or item.endswith(".overload") for item in decorators)


def _is_never_call(expression: ast.expr, never_functions: frozenset[str]) -> bool:
    return (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id in never_functions
    )
