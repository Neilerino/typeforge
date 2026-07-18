import ast
from dataclasses import dataclass
from pathlib import Path

from returns.result import Failure, Result, Success

from typeforge.analysis.model import SourcePosition, SourceSpan
from typeforge.analysis.positions import source_position_from_utf8
from typeforge.compiler.emitter import emit_type_expression
from typeforge.compiler.lowering import TypeExpression
from typeforge.compiler.model import SourceModule
from typeforge.compiler.pipeline import (
    AdaptationError,
    SemanticRelationshipAlias,
)
from typeforge.verification.contracts import aggregate_output, build_return_contract
from typeforge.verification.guards import recognize_guard, recognize_pattern
from typeforge.verification.model import (
    Alternative,
    FlowState,
    Guard,
    GuardMode,
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
    source: str
    contract: ReturnContract
    never_functions: frozenset[str]


def plan_implementation_verification(
    source: str,
    path: Path,
    module: SourceModule,
    tree: ast.Module,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> Result[VerificationPlan, AdaptationError]:
    del path
    nodes = _function_nodes(tree)
    never_functions = frozenset(
        function.name
        for function in module.functions
        if function.returns is not None
        and function.returns.source in {"Never", "NoReturn", "typing.Never"}
    )
    obligations: list[ReturnObligation] = []
    for function in module.functions:
        node = nodes.get((function.qualified_name, function.span.start.line))
        if (
            node is None
            or _is_generator(node)
            or _is_declaration_only(node)
            or _is_overload(function.decorators)
        ):
            continue
        enclosing = _enclosing_type_parameters(module, function.qualified_name)
        contract_result = build_return_contract(function, aliases, enclosing)
        if isinstance(contract_result, Failure):
            return contract_result
        contract = contract_result.unwrap()
        if contract is None:
            continue
        initial = FlowState(tuple(item.index for item in contract.alternatives))
        context = _PlanningContext(source, contract, never_functions)
        analyzed = _analyze_statements(node.body, (initial,), context)
        obligations.extend(analyzed.obligations)
        obligations.extend(_fallthrough_obligations(node, analyzed.continuing, context))
    reserved = tuple(
        sorted(
            {item.id for item in ast.walk(tree) if isinstance(item, ast.Name)}
            | {
                argument.arg
                for item in ast.walk(tree)
                if isinstance(item, ast.arguments)
                for argument in (
                    *item.posonlyargs,
                    *item.args,
                    *item.kwonlyargs,
                    *((item.vararg,) if item.vararg is not None else ()),
                    *((item.kwarg,) if item.kwarg is not None else ()),
                )
            }
        )
    )
    return Success(VerificationPlan(tuple(obligations), reserved))


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
    rendered = {item.index: _normalize_type(_render_input(item)) for item in available}
    guard_types = tuple(
        normalized
        for item in guard.type_names
        if (normalized := _normalize_type(item)) is not None
    )
    explicit_matches = {
        item.index
        for item in available
        if not item.is_default and rendered[item.index] in guard_types
    }
    unresolved = {
        item.index
        for item in available
        if not item.is_default and rendered[item.index] is None
    }
    if guard.mode is GuardMode.INSTANCE:
        explicit_matches.update(
            item.index
            for item in available
            if not item.is_default
            and _known_runtime_subclass(rendered[item.index], guard_types)
        )
        default = next((item for item in available if item.is_default), None)
        positive_indices = explicit_matches | unresolved
        if default is not None and _render_output(default) != "Never":
            positive_indices.add(default.index)
        negative_indices = unresolved | {
            item.index for item in available if item.index not in explicit_matches
        }
    else:
        default = next((item for item in available if item.is_default), None)
        positive_indices = explicit_matches | unresolved
        if not positive_indices and default is not None:
            positive_indices.add(default.index)
        negative_indices = unresolved | {
            item.index for item in available if item.index not in explicit_matches
        }
    return (
        FlowState(
            tuple(sorted(positive_indices)),
            not unresolved,
            state.controller_valid,
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
    expression = statement.value
    expression_text = (
        ast.get_source_segment(context.source, expression)
        if expression is not None
        else None
    ) or "None"
    expression_span = (
        _node_span(context.source, expression)
        if expression is not None
        else _node_span(context.source, statement)
    )
    expected = _expected_types(state, context.contract)
    insertion = _node_span(context.source, statement).start
    line_start = context.source.rfind("\n", 0, insertion.offset) + 1
    prefix = context.source[line_start : insertion.offset]
    inline = bool(prefix.strip())
    indentation = "" if inline else prefix
    return ReturnObligation(
        qualified_name=context.contract.qualified_name,
        return_annotation=context.contract.return_annotation,
        controller_parameter=context.contract.controller_parameter,
        expected_types=expected,
        narrowed_inputs=tuple(
            value
            for item in context.contract.alternatives
            if item.index in state.alternatives
            and not item.is_default
            and (value := _render_input(item)) is not None
        ),
        expression_text=expression_text,
        expression_span=expression_span,
        insertion_offset=insertion.offset,
        indentation=indentation,
        inline=inline,
    )


def _fallthrough_obligations(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    states: tuple[FlowState, ...],
    context: _PlanningContext,
) -> tuple[ReturnObligation, ...]:
    if not states or not node.body:
        return ()
    state = _merged_state(states)
    end = _node_span(context.source, node.body[-1]).end
    line_end = context.source.find("\n", end.offset)
    insertion_offset = len(context.source) if line_end < 0 else line_end + 1
    position = _position(context.source, insertion_offset)
    return (
        ReturnObligation(
            qualified_name=context.contract.qualified_name,
            return_annotation=context.contract.return_annotation,
            controller_parameter=context.contract.controller_parameter,
            expected_types=_expected_types(state, context.contract),
            narrowed_inputs=(),
            expression_text="None",
            expression_span=SourceSpan(position, position),
            insertion_offset=insertion_offset,
            indentation=" " * (node.col_offset + 4),
            inline=False,
            starts_line=True,
            leading_newline=line_end < 0,
        ),
    )


def _expected_types(
    state: FlowState, contract: ReturnContract
) -> tuple[TypeExpression, ...]:
    if not state.refined or not state.controller_valid:
        return (aggregate_output(contract),)
    values = tuple(
        item.output_type
        for item in contract.alternatives
        if item.index in state.alternatives
    )
    deduplicated: list[TypeExpression] = []
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


def _render_input(alternative: Alternative) -> str | None:
    if alternative.input_type is None:
        return None
    return emit_type_expression(alternative.input_type).value_or(None)


def _render_output(alternative: Alternative) -> str | None:
    return emit_type_expression(alternative.output_type).value_or(None)


def _known_runtime_subclass(candidate: str | None, parents: tuple[str, ...]) -> bool:
    return candidate == "bool" and "int" in parents


def _normalize_type(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return ast.unparse(ast.parse(value, mode="eval").body)
    except SyntaxError:
        return value


def _function_nodes(
    tree: ast.Module,
) -> dict[tuple[tuple[str, ...], int], ast.FunctionDef | ast.AsyncFunctionDef]:
    nodes: dict[
        tuple[tuple[str, ...], int], ast.FunctionDef | ast.AsyncFunctionDef
    ] = {}

    def visit(statements: list[ast.stmt], scope: tuple[str, ...]) -> None:
        for statement in statements:
            if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
                nodes[((*scope, statement.name), statement.lineno)] = statement
            elif isinstance(statement, ast.ClassDef):
                visit(statement.body, (*scope, statement.name))
            elif isinstance(statement, ast.If | ast.While | ast.For | ast.AsyncFor):
                visit(statement.body, scope)
                visit(statement.orelse, scope)
            elif isinstance(statement, ast.Try | ast.TryStar):
                visit(statement.body, scope)
                for handler in statement.handlers:
                    visit(handler.body, scope)
                visit(statement.orelse, scope)
                visit(statement.finalbody, scope)
            elif isinstance(statement, ast.With | ast.AsyncWith):
                visit(statement.body, scope)
            elif isinstance(statement, ast.Match):
                for case in statement.cases:
                    visit(case.body, scope)

    visit(tree.body, ())
    return nodes


def _enclosing_type_parameters(
    module: SourceModule, qualified_name: tuple[str, ...]
) -> tuple[str, ...]:
    if len(qualified_name) != 2:
        return ()
    owner = next(
        (item for item in module.classes if item.name == qualified_name[0]),
        None,
    )
    return () if owner is None else tuple(item.name for item in owner.type_parameters)


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


def _node_span(source: str, node: ast.AST) -> SourceSpan:
    lineno = getattr(node, "lineno", 1)
    column = getattr(node, "col_offset", 0)
    end_lineno = getattr(node, "end_lineno", lineno)
    end_column = getattr(node, "end_col_offset", column)
    return SourceSpan(
        source_position_from_utf8(source, lineno - 1, column),
        source_position_from_utf8(source, end_lineno - 1, end_column),
    )


def _position(source: str, offset: int) -> SourcePosition:
    prefix = source[:offset]
    line = prefix.count("\n")
    previous = prefix.rfind("\n")
    column = offset if previous < 0 else offset - previous - 1
    return SourcePosition(offset, line, column)
