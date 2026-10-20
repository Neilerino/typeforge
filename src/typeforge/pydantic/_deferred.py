"""Observe raw Input and emit validation of shared deferred selections."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import (
    Annotated,
    Literal,
    TypeAliasType,
    Union,
    cast,
    get_args,
    get_origin,
)

from pydantic_core import (
    CoreSchema,
    InitErrorDetails,
    PydanticCustomError,
    ValidationError,
    core_schema,
)
from returns.result import Failure

from pydantic import GetCoreSchemaHandler
from typeforge import semantics as s
from typeforge.pydantic._emission import emit_output
from typeforge.pydantic._evaluation import evaluation_issue, schema_output
from typeforge.pydantic._frontend import AdaptedAnnotation
from typeforge.pydantic._observation import RawInput, input_test_kinds, matches_type
from typeforge.pydantic._policy import input_test_issue
from typeforge.pydantic._type_system import (
    RUNTIME_TYPE_SYSTEM,
    RuntimeType,
    concrete_type,
)
from typeforge.utils.error_handling import safe_result

# Pydantic's stubs require literal strings; forwarded diagnostics carry runtime
# codes and messages. Keep that typing adaptation at the CoreSchema boundary.
_custom_error = cast(
    Callable[[str, str, dict[str, object] | None], PydanticCustomError],
    PydanticCustomError,
)


_DEFER_ERRORS: tuple[type[s.SemanticIssue | s.MapNoMatch[RuntimeType]], ...] = (
    s.SemanticIssue,
    s.MapNoMatch,
)


@dataclass(frozen=True, slots=True)
class DeferredAnnotations:
    """Keep deferred plans in runtime types while shared traversal composes them."""

    adapted: AdaptedAnnotation
    source: object

    @safe_result(errors=_DEFER_ERRORS)
    def defer(self, plan: s.DeferredMap[RuntimeType]) -> RuntimeType:
        evaluator = s.Evaluator(
            RUNTIME_TYPE_SYSTEM,
            deferred_types=self,
            context=plan.context,
        )
        expressions = tuple(case.output for case in plan.cases)
        if plan.default is not None:
            expressions = (*expressions, plan.default)

        outputs = tuple(evaluator.evaluate(output).unwrap() for output in expressions)
        source = self.adapted.origins.get(id(plan.expression), self.source)
        return concrete_type(_InputAnnotation(plan, outputs, self.adapted, source))


@dataclass(frozen=True, slots=True, eq=False)
class _InputAnnotation:
    plan: s.DeferredMap[RuntimeType]
    outputs: tuple[s.EvaluationValue[RuntimeType], ...]
    adapted: AdaptedAnnotation
    source: object

    def __get_pydantic_core_schema__(
        self, source: object, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        for case in self.plan.cases:
            for kind in input_test_kinds(case.test, self.plan.context):
                issue = input_test_issue(kind, self.source)
                if issue is not None:
                    raise issue

        choices = {
            index: emit_output(
                schema_output(output, self.source).unwrap(),
                handler.generate_schema,
                self.source,
            ).unwrap()
            for index, output in enumerate(self.outputs)
        }
        return _dispatch_schema(self, choices)


def _output_matches(output: s.EvaluationValue[RuntimeType], value: object) -> bool:
    if isinstance(output, s.RecordShape):
        return isinstance(value, dict)

    if isinstance(output, s.ResolvedType):
        return _output_type_matches(output.value.value, value)

    return False


def _output_type_matches(target: object, value: object) -> bool:
    if isinstance(target, _InputAnnotation):
        return any(_output_matches(item, value) for item in target.outputs)

    origin = get_origin(target)
    if origin is Annotated:
        return _output_type_matches(get_args(target)[0], value)

    if origin is Union:
        return any(_output_type_matches(item, value) for item in get_args(target))

    if isinstance(target, TypeAliasType):
        return _output_type_matches(target.__value__, value)

    if origin is not None and origin is not Literal:
        return type(value) is origin

    return matches_type(target, value)


def _dispatch_schema(
    annotation: _InputAnnotation, choices: dict[int, CoreSchema]
) -> CoreSchema:
    evaluator = s.Evaluator(RUNTIME_TYPE_SYSTEM)

    def select(value: object) -> int:
        selected = evaluator.select_deferred_map(
            annotation.plan, concrete_type(type(value)), RawInput(value)
        )
        if isinstance(selected, Failure):
            issue = evaluation_issue(
                selected.failure(), annotation.adapted, annotation.source
            )
            raise _custom_error(
                f"typeforge_{issue.code}",
                "{message}",
                {"message": issue.render()},
            )

        index = selected.unwrap().case_index
        return len(annotation.plan.cases) if index is None else index

    if not choices:
        return core_schema.no_info_plain_validator_function(
            select,
            json_schema_input_schema=core_schema.any_schema(),
            serialization=core_schema.wrap_serializer_function_ser_schema(
                _serialize_output,
                schema=core_schema.any_schema(),
                return_schema=core_schema.any_schema(),
            ),
        )

    def output_branch(value: object) -> int:
        return next(
            (
                index
                for index, output in enumerate(annotation.outputs)
                if _output_matches(output, value)
            ),
            0,
        )

    return core_schema.no_info_wrap_validator_function(
        _validate_branch,
        core_schema.tagged_union_schema(choices, discriminator=select),
        json_schema_input_schema=core_schema.any_schema(),
        serialization=core_schema.wrap_serializer_function_ser_schema(
            _serialize_output,
            schema=core_schema.tagged_union_schema(
                choices, discriminator=output_branch
            ),
            return_schema=core_schema.any_schema(),
        ),
    )


def _validate_branch(
    value: object, handler: core_schema.ValidatorFunctionWrapHandler
) -> object:
    try:
        return handler(value)
    except ValidationError as error:
        # Pydantic's private branch index is not an authored field location.
        errors: list[InitErrorDetails] = [
            InitErrorDetails(
                type=_custom_error(
                    detail["type"],
                    detail["msg"],
                    detail.get("ctx"),
                ),
                loc=detail["loc"][1:] if detail["loc"] else (),
                input=detail["input"],
            )
            for detail in error.errors(include_url=False)
        ]
        raise ValidationError.from_exception_data("Typeforge Input", errors) from error


def _serialize_output(
    value: object, handler: core_schema.SerializerFunctionWrapHandler
) -> object:
    return handler(value)
