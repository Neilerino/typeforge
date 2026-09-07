"""Shared semantic evaluation interface and private traversal."""

from dataclasses import replace
from functools import singledispatch

from returns.result import Result

from typeforge.semantics.domain.assertions import (
    expect_condition,
    expect_field,
    expect_field_name,
    expect_type,
    expect_type_value,
)
from typeforge.semantics.domain.exceptions import (
    DuplicateFieldSemanticError,
    SemanticIssue,
    UnboundInputSemanticError,
    UnboundKeySemanticError,
    UnboundValueSemanticError,
    UnsupportedExpressionSemanticError,
)
from typeforge.semantics.domain.models import (
    AllExpression,
    AnyExpression,
    AssignableExpression,
    DeferredMap,
    DropExpression,
    DroppedField,
    EqualExpression,
    EvaluationContext,
    EvaluationValue,
    Expression,
    FieldExpression,
    FieldName,
    IndeterminateCondition,
    InputReference,
    KeyReference,
    MapExpression,
    MapFieldsExpression,
    NotExpression,
    OptionalFieldExpression,
    ParameterizedTypeShape,
    ParameterizedTypeTemplate,
    ReadonlyFieldExpression,
    RecordField,
    ResolvedType,
    TypeReference,
    TypeValue,
    TypeValueReference,
    UnionExpression,
    ValueReference,
)
from typeforge.semantics.map_evaluation import evaluate_map
from typeforge.semantics.protocols import TypeSystem
from typeforge.semantics.type_evaluation import (
    assignable_types,
    build_type,
    conjunction,
    disjunction,
    equal_types,
    union_type,
)
from typeforge.utils.error_handling import safe_result


def evaluate[T](
    expression: Expression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T] | None = None,
) -> Result[EvaluationValue[T], SemanticIssue]:
    """Evaluate a normalized expression through a type-system adapter."""
    evaluation_context = EvaluationContext[T]() if context is None else context

    eval_safely = safe_result(errors=(SemanticIssue,))(_evaluate)
    return eval_safely(expression, type_system, evaluation_context)


@singledispatch
def _evaluate[T](
    expression: Expression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    raise UnsupportedExpressionSemanticError(
        f"unsupported expression {type(expression).__name__}"
    )


@_evaluate.register(TypeReference)
def _[T](
    expression: TypeReference[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return ResolvedType(expression.value)


@_evaluate.register(FieldName)
def _[T](
    expression: FieldName,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return expression


@_evaluate.register(TypeValueReference)
def _[T](
    expression: TypeValueReference[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return expression.value


@_evaluate.register(InputReference)
def _[T](
    expression: InputReference,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    if context.input_type is None:
        raise UnboundInputSemanticError("Input requires value-time evaluation")

    return context.input_type


@_evaluate.register(KeyReference)
def _[T](
    expression: KeyReference,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    if context.key is None:
        raise UnboundKeySemanticError("Key requires MapFields")

    return FieldName(context.key)


@_evaluate.register(ValueReference)
def _[T](
    expression: ValueReference,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    if context.capture is not None:
        return context.capture

    if context.value is not None:
        return context.value

    raise UnboundValueSemanticError("Value requires MapFields or a structural Map case")


@_evaluate.register(DropExpression)
def _[T](
    expression: DropExpression,
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return DroppedField()


@_evaluate.register(ParameterizedTypeTemplate)
def _[T](
    expression: ParameterizedTypeTemplate[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    arguments: list[TypeValue[T]] = []
    for argument in expression.arguments:
        value = _evaluate(argument, type_system, context)
        # A deferred argument contributes its existing bound; static uncertainty
        # keeps its provenance for later predicates.
        arguments.append(
            expect_type_value(
                value.possible_output if isinstance(value, DeferredMap) else value,
                "parameterized type arguments must evaluate to types",
            )
        )

    shape = ParameterizedTypeShape(ResolvedType(expression.origin), tuple(arguments))
    return build_type(shape, type_system)


@_evaluate.register(FieldExpression | OptionalFieldExpression | ReadonlyFieldExpression)
def _[T](
    expression: (
        FieldExpression[T] | OptionalFieldExpression[T] | ReadonlyFieldExpression[T]
    ),
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    name = expect_field_name(_evaluate(expression.name, type_system, context))
    value = expect_type(
        _evaluate(expression.value, type_system, context),
        "field value must evaluate to a type",
    )

    return RecordField(
        name.value,
        value.value,
        required=not isinstance(expression, OptionalFieldExpression),
        readonly=isinstance(expression, ReadonlyFieldExpression),
    )


@_evaluate.register(MapFieldsExpression)
def _[T](
    expression: MapFieldsExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    record_type = expect_type(
        _evaluate(expression.record, type_system, context),
    )
    record = type_system.record(record_type.value).unwrap()
    fields: list[RecordField[T]] = []
    field_names: set[str] = set()

    for source_field in record.fields:
        field_context = replace(
            context,
            key=source_field.name,
            value=ResolvedType(source_field.value),
        )
        transformed = _evaluate(expression.transform, type_system, field_context)
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
            record.name if expression.output_name is None else expression.output_name
        ),
        fields=tuple(fields),
    )


@_evaluate.register(UnionExpression)
def _[T](
    expression: UnionExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return union_type(
        (_evaluate(member, type_system, context) for member in expression.members),
        type_system,
        "union members must evaluate to types",
    )


@_evaluate.register(EqualExpression)
def _[T](
    expression: EqualExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    left = _evaluate(expression.left, type_system, context)
    right = _evaluate(expression.right, type_system, context)

    if isinstance(left, FieldName) and isinstance(right, FieldName):
        return left == right

    message = "Equal operands must both be types or both be field names"
    return equal_types(
        expect_type_value(left, message), expect_type_value(right, message), type_system
    )


@_evaluate.register(AssignableExpression)
def _[T](
    expression: AssignableExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    source = expect_type_value(
        _evaluate(expression.source, type_system, context),
        "Assignable operands must both be types",
    )
    target = expect_type_value(
        _evaluate(expression.target, type_system, context),
        "Assignable operands must both be types",
    )

    return assignable_types(source, target, type_system)


@_evaluate.register(AnyExpression | AllExpression)
def _[T](
    expression: AllExpression[T] | AnyExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    conditions = (
        expect_condition(_evaluate(condition, type_system, context))
        for condition in expression.conditions
    )
    return (
        conjunction(conditions)
        if isinstance(expression, AllExpression)
        else disjunction(conditions)
    )


@_evaluate.register(NotExpression)
def _[T](
    expression: NotExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    value = expect_condition(_evaluate(expression.condition, type_system, context))
    return value if isinstance(value, IndeterminateCondition) else not value


@_evaluate.register(MapExpression)
def _[T](
    expression: MapExpression[T],
    type_system: TypeSystem[T],
    context: EvaluationContext[T],
) -> EvaluationValue[T]:
    return evaluate_map(expression, type_system, context, fn=_evaluate)
