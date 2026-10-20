"""Shared semantic evaluation interface and private traversal."""

from collections.abc import Callable, Iterator
from dataclasses import replace
from functools import singledispatchmethod
from typing import assert_never

from returns.result import Failure, Result

from typeforge.semantics.domain.assertions import (
    expect_condition,
    expect_field,
    expect_field_name,
    expect_possible_type,
    expect_type,
    expect_type_value,
)
from typeforge.semantics.domain.exceptions import (
    DuplicateFieldSemanticError,
    SemanticIssue,
    UnboundCaptureSemanticError,
    UnboundInputSemanticError,
    UnboundKeySemanticError,
    UnboundValueSemanticError,
    UnsupportedExpressionSemanticError,
)
from typeforge.semantics.domain.models import (
    AllExpression,
    AnnotatedExpression,
    AnyExpression,
    AssignableExpression,
    CaptureReference,
    Condition,
    DeferredMap,
    DropExpression,
    DroppedField,
    EqualExpression,
    EvaluationContext,
    EvaluationMode,
    EvaluationValue,
    Expression,
    FieldExpression,
    FieldName,
    IndeterminateCondition,
    IndeterminateType,
    InputReference,
    KeyReference,
    MapExpression,
    MapFieldsExpression,
    MapNoMatch,
    MapSelection,
    NoMatchDecision,
    NotExpression,
    OptionalFieldExpression,
    ParameterizedTypeShape,
    ParameterizedTypeTemplate,
    ReadonlyFieldExpression,
    RecordField,
    RecordShape,
    ResolvedType,
    TypePattern,
    TypeReference,
    TypeValue,
    TypeValueReference,
    UnionExpression,
    UnresolvedType,
    ValueReference,
    is_bool_expr,
    is_pattern_expr,
)
from typeforge.semantics.map_matching import map_values_match, match_map_pattern
from typeforge.semantics.protocols import (
    DeferredTypes,
    EvaluationPolicy,
    InputObserver,
    TypeSystem,
)
from typeforge.semantics.type_evaluation import (
    assignable_types,
    build_type,
    conjunction,
    disjunction,
    equal_types,
    indeterminate_type,
    union_members,
    union_type,
)
from typeforge.utils.error_handling import safe_result


class _DefaultPolicy[T]:
    def no_match(self, outcome: MapNoMatch[T]) -> NoMatchDecision:
        return (
            NoMatchDecision.REJECT
            if outcome.context.mode is EvaluationMode.DEFINITE
            else NoMatchDecision.ACCEPT
        )


def evaluate[T](
    expression: Expression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T] | None = None,
) -> Result[EvaluationValue[T], SemanticIssue | MapNoMatch[T]]:
    """Reject reached uncovered subjects; allow speculative output-bound exploration."""
    return Evaluator(type_system, context=context).evaluate(expression)


class Evaluator[T]:
    """Shared traversal composed with type operations and acceptance policy.

    Each evaluator binds an immutable context to shared dependencies. Derived
    bindings and speculative paths use child evaluators, leaving parents unchanged.
    """

    def __init__(
        self,
        type_system: TypeSystem[T],
        *,
        policy: EvaluationPolicy[T] | None = None,
        context: EvaluationContext[T] | None = None,
        deferred_types: DeferredTypes[T] | None = None,
    ) -> None:
        self.type_system = type_system
        self._policy: EvaluationPolicy[T] = policy or _DefaultPolicy()
        self._context: EvaluationContext[T] = context or EvaluationContext()
        self._deferred_types = deferred_types

    @property
    def context(self) -> EvaluationContext[T]:
        return self._context

    def with_context(self, context: EvaluationContext[T]) -> Evaluator[T]:
        """Bind a child context while sharing this evaluator's adapter and policy."""
        return Evaluator(
            self.type_system,
            policy=self._policy,
            context=context,
            deferred_types=self._deferred_types,
        )

    def select_deferred_map(
        self, plan: DeferredMap[T], input_type: T, observer: InputObserver[T]
    ) -> Result[MapSelection[T], SemanticIssue | MapNoMatch[T]]:
        """Resume a deferred Map, stopping before its selected output is evaluated.

        Restore the plan's saved bindings and bind the observed input type.
        Return no-match evidence directly, without applying output acceptance policy.
        """
        errors: tuple[type[SemanticIssue | MapNoMatch[T]], ...] = (
            SemanticIssue,
            MapNoMatch,
        )
        run: Callable[
            [DeferredMap[T], T, InputObserver[T]],
            Result[MapSelection[T], SemanticIssue | MapNoMatch[T]],
        ] = safe_result(errors=errors)(self._select_deferred_map)
        return run(plan, input_type, observer)

    def _select_deferred_map(
        self, plan: DeferredMap[T], input_type: T, observer: InputObserver[T]
    ) -> MapSelection[T]:
        subject = ResolvedType(input_type)
        evaluator = self.with_context(replace(plan.context, input_type=subject))
        expression = plan.expression or MapExpression(
            InputReference(), plan.cases, plan.default
        )
        selection = evaluator._select_map_member(subject, expression, observer=observer)
        if isinstance(selection, MapNoMatch):
            return Failure(selection).unwrap()

        return selection

    def evaluate(
        self, expression: Expression[T]
    ) -> Result[EvaluationValue[T], SemanticIssue | MapNoMatch[T]]:
        errors: tuple[type[SemanticIssue | MapNoMatch[T]], ...] = (
            SemanticIssue,
            MapNoMatch,
        )
        run: Callable[
            [Expression[T]],
            Result[EvaluationValue[T], SemanticIssue | MapNoMatch[T]],
        ] = safe_result(errors=errors)(self._evaluate)
        return run(expression)

    def _no_match(self, outcome: MapNoMatch[T]) -> ResolvedType[T]:
        match self._policy.no_match(outcome):
            case NoMatchDecision.REJECT:
                return Failure(outcome).unwrap()
            case NoMatchDecision.ACCEPT:
                return ResolvedType(self.type_system.union(()).unwrap())
            case _ as unreachable:
                assert_never(unreachable)

    def _evaluate(self, expression: Expression[T]) -> EvaluationValue[T]:
        # singledispatchmethod's descriptor typing erases the class type parameter.
        # Preserve that relationship for recursive calls and the result boundary.
        return self._dispatch(expression)

    @singledispatchmethod
    def _dispatch(self, expression: Expression[T]) -> EvaluationValue[T]:
        raise UnsupportedExpressionSemanticError(
            f"unsupported expression {type(expression).__name__}"
        )

    @_dispatch.register(TypeReference)
    def _type_reference(self, expression: TypeReference[T]) -> EvaluationValue[T]:
        return ResolvedType(expression.value)

    @_dispatch.register(FieldName)
    def _field_name(self, expression: FieldName) -> EvaluationValue[T]:
        return expression

    @_dispatch.register(TypeValueReference)
    def _type_value_reference(
        self, expression: TypeValueReference[T]
    ) -> EvaluationValue[T]:
        return expression.value

    @_dispatch.register(InputReference)
    def _input(self, expression: InputReference) -> EvaluationValue[T]:
        if self.context.input_type is None:
            raise UnboundInputSemanticError("Input requires value-time evaluation")

        return self.context.input_type

    @_dispatch.register(KeyReference)
    def _key(self, expression: KeyReference) -> EvaluationValue[T]:
        if self.context.key is None:
            raise UnboundKeySemanticError("Key requires MapFields")

        return FieldName(self.context.key)

    @_dispatch.register(ValueReference)
    def _value(self, expression: ValueReference) -> EvaluationValue[T]:
        if self.context.value is not None:
            return self.context.value

        raise UnboundValueSemanticError("Value requires MapFields")

    @_dispatch.register(CaptureReference)
    def _capture(self, expression: CaptureReference) -> EvaluationValue[T]:
        bound = dict(self.context.captures).get(expression.symbol)
        if bound is None:
            raise UnboundCaptureSemanticError(
                f"capture {expression.symbol.name!r} is unbound"
            )

        return bound

    @_dispatch.register(DropExpression)
    def _drop(self, expression: DropExpression) -> EvaluationValue[T]:
        return DroppedField()

    @_dispatch.register(ParameterizedTypeTemplate)
    def _template(self, expression: ParameterizedTypeTemplate[T]) -> EvaluationValue[T]:
        arguments: list[TypeValue[T]] = []
        for argument in expression.arguments:
            value = self._evaluate(argument)
            # Deferred arguments contribute their existing bounds; static
            # uncertainty keeps its provenance for later predicates.
            arguments.append(
                expect_type_value(
                    expect_possible_type(value, "deferred argument requires a bound")
                    if isinstance(value, DeferredMap)
                    else value,
                    "parameterized type arguments must evaluate to types",
                )
            )

        shape = ParameterizedTypeShape(
            ResolvedType(expression.origin), tuple(arguments)
        )
        return build_type(shape, self.type_system)

    @_dispatch.register(AnnotatedExpression)
    def _annotated(self, expression: AnnotatedExpression[T]) -> EvaluationValue[T]:
        value = self._evaluate(expression.value)
        if isinstance(value, RecordShape):
            return replace(value, metadata=(*value.metadata, *expression.metadata))

        annotated = expect_type_value(
            expect_possible_type(value, "deferred annotation requires a bound")
            if isinstance(value, DeferredMap)
            else value,
            "annotations require a type or a record",
        )
        return build_type(
            ParameterizedTypeShape(
                ResolvedType(expression.origin),
                (annotated, *(ResolvedType(item) for item in expression.metadata)),
            ),
            self.type_system,
        )

    @_dispatch.register(
        FieldExpression | OptionalFieldExpression | ReadonlyFieldExpression
    )
    def _field(
        self,
        expression: FieldExpression[T]
        | OptionalFieldExpression[T]
        | ReadonlyFieldExpression[T],
    ) -> EvaluationValue[T]:
        name = expect_field_name(self._evaluate(expression.name))
        value = expect_type(
            self._evaluate(expression.value),
            "field value must evaluate to a type",
        )

        return RecordField(
            name.value,
            value.value,
            required=not isinstance(expression, OptionalFieldExpression),
            readonly=isinstance(expression, ReadonlyFieldExpression),
        )

    @_dispatch.register(MapFieldsExpression)
    def _map_fields(self, expression: MapFieldsExpression[T]) -> EvaluationValue[T]:
        record_type = expect_type(
            self._evaluate(expression.record),
        )
        record = self.type_system.record(record_type.value).unwrap()
        fields: list[RecordField[T]] = []
        field_names: set[str] = set()

        for source_field in record.fields:
            field_context = replace(
                self.context,
                key=source_field.name,
                value=ResolvedType(source_field.value),
            )
            transformed = self.with_context(field_context)._evaluate(
                expression.transform
            )
            if isinstance(transformed, DroppedField):
                continue

            field = expect_field(
                transformed,
                "MapFields transform must evaluate to a field or Drop",
            )
            if field.name in field_names:
                raise DuplicateFieldSemanticError(
                    f"multiple source fields produce {field.name!r}"
                )

            field_names.add(field.name)
            fields.append(field)

        return replace(
            record,
            name=(
                record.name
                if expression.output_name is None
                else expression.output_name
            ),
            fields=tuple(fields),
        )

    @_dispatch.register(UnionExpression)
    def _union(self, expression: UnionExpression[T]) -> EvaluationValue[T]:
        return union_type(
            (self._evaluate(member) for member in expression.members),
            self.type_system,
            "union members must evaluate to types",
        )

    @_dispatch.register(EqualExpression)
    def _equal(self, expression: EqualExpression[T]) -> EvaluationValue[T]:
        left = self._evaluate(expression.left)
        right = self._evaluate(expression.right)

        if isinstance(left, FieldName) and isinstance(right, FieldName):
            return left == right

        message = "Equal operands must both be types or both be field names"
        return equal_types(
            expect_type_value(left, message),
            expect_type_value(right, message),
            self.type_system,
        )

    @_dispatch.register(AssignableExpression)
    def _assignable(self, expression: AssignableExpression[T]) -> EvaluationValue[T]:
        source = expect_type_value(
            self._evaluate(expression.source),
            "Assignable operands must both be types",
        )
        target = expect_type_value(
            self._evaluate(expression.target),
            "Assignable operands must both be types",
        )

        return assignable_types(source, target, self.type_system)

    @_dispatch.register(AnyExpression | AllExpression)
    def _conditions(
        self,
        expression: AnyExpression[T] | AllExpression[T],
    ) -> EvaluationValue[T]:
        def conditions() -> Iterator[Condition]:
            evaluator = self
            for condition in expression.conditions:
                value = expect_condition(evaluator._evaluate(condition))
                yield value
                if isinstance(value, IndeterminateCondition):
                    evaluator = self.with_context(
                        replace(self.context, mode=EvaluationMode.SPECULATIVE)
                    )

        return (
            conjunction(conditions())
            if isinstance(expression, AllExpression)
            else disjunction(conditions())
        )

    @_dispatch.register(NotExpression)
    def _not(self, expression: NotExpression[T]) -> EvaluationValue[T]:
        value = expect_condition(self._evaluate(expression.condition))
        return value if isinstance(value, IndeterminateCondition) else not value

    @_dispatch.register(MapExpression)
    def _map(self, expression: MapExpression[T]) -> EvaluationValue[T]:
        return self._evaluate_map(expression)

    def _evaluate_map(
        self,
        expression: MapExpression[T],
    ) -> EvaluationValue[T]:
        if (
            isinstance(expression.subject, InputReference)
            and self.context.input_type is None
        ):
            return self._defer_map(expression)

        subject = self._evaluate(expression.subject)
        members: tuple[EvaluationValue[T], ...]
        if isinstance(subject, ResolvedType | UnresolvedType):
            members = union_members(subject, self.type_system)
        else:
            members = (subject,)

        outputs = tuple(
            self._evaluate_map_member(member, expression) for member in members
        )
        if len(outputs) == 1:
            return outputs[0]

        return union_type(
            outputs,
            self.type_system,
            "Map outputs for a union subject must evaluate to types",
        )

    def _defer_map(
        self,
        expression: MapExpression[T],
    ) -> DeferredMap[T] | ResolvedType[T]:
        plan = DeferredMap(
            expression.cases, expression.default, self.context, expression=expression
        )
        if self._deferred_types is not None:
            return ResolvedType(self._deferred_types.defer(plan).unwrap())

        speculative = self.with_context(
            replace(self.context, mode=EvaluationMode.SPECULATIVE)
        )
        output_types = tuple(
            expect_possible_type(
                speculative._evaluate(case.output),
                "deferred Map outputs must evaluate to types",
            ).value
            for case in expression.cases
        )
        if expression.default is not None:
            default_type = expect_possible_type(
                speculative._evaluate(expression.default),
                "deferred Map outputs must evaluate to types",
            )
            output_types = (*output_types, default_type.value)

        return replace(
            plan,
            possible_output=ResolvedType(self.type_system.union(output_types).unwrap()),
        )

    def _evaluate_map_member(
        self,
        subject: EvaluationValue[T],
        expression: MapExpression[T],
        *,
        start_case: int = 0,
    ) -> EvaluationValue[T]:
        selection = self._select_map_member(subject, expression, start_case=start_case)
        if isinstance(selection, MapNoMatch):
            return self._no_match(selection)

        if selection.condition is True:
            return self.with_context(selection.context)._evaluate(selection.output)

        assert isinstance(selection.condition, IndeterminateCondition)
        assert selection.case_index is not None
        speculative = self.with_context(
            replace(self.context, mode=EvaluationMode.SPECULATIVE)
        )
        selected = self.with_context(
            replace(selection.context, mode=EvaluationMode.SPECULATIVE)
        )._evaluate(selection.output)
        expect_possible_type(
            selected, "indeterminate Map outputs must evaluate to types"
        )
        remaining = speculative._evaluate_map_member(
            subject, expression, start_case=selection.case_index + 1
        )
        return indeterminate_type((selected, remaining), self.type_system)

    def _select_map_member(
        self,
        subject: EvaluationValue[T],
        expression: MapExpression[T],
        *,
        start_case: int = 0,
        observer: InputObserver[T] | None = None,
    ) -> MapSelection[T] | MapNoMatch[T]:
        for index, case in enumerate(expression.cases[start_case:], start=start_case):
            output_context = self.context
            if observer is not None:
                matched = self._observe_test(case.test, observer)

            elif is_bool_expr(case.test):
                matched = expect_condition(self._evaluate(case.test))

            elif is_pattern_expr(case.test):
                if isinstance(
                    subject, ResolvedType | UnresolvedType | IndeterminateType
                ):
                    pattern_match = match_map_pattern(
                        case.test,
                        subject,
                        self.type_system,
                        self.context.captures,
                    )
                    matched = pattern_match.matched
                    output_context = replace(
                        self.context,
                        captures=pattern_match.captures,
                    )
                else:
                    matched = False

            else:
                test = self._evaluate(case.test)
                matched = map_values_match(subject, test, self.type_system)

            if matched is True or isinstance(matched, IndeterminateCondition):
                return MapSelection(case.output, output_context, index, matched)

        if expression.default is not None:
            return MapSelection(expression.default, self.context, None)

        return MapNoMatch(expression, subject, self.context)

    def _observe_test(
        self, test: Expression[T] | TypePattern[T], observer: InputObserver[T]
    ) -> Condition:
        if is_bool_expr(test):
            return expect_condition(self._evaluate(test))

        match test:
            case UnionExpression(members=members):
                return disjunction(
                    self._observe_test(member, observer) for member in members
                )

            case AnnotatedExpression(value=value):
                return self._observe_test(value, observer)

            case _:
                return observer.matches(test, self.context).unwrap()
