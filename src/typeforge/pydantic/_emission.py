"""Pydantic schemas for resolved types and uninhabited generic fallback fields."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Never

from pydantic_core import CoreSchema, PydanticCustomError, core_schema

from pydantic import GetCoreSchemaHandler, PydanticSchemaGenerationError
from typeforge import semantics as s
from typeforge.pydantic._errors import (
    MapNoMatchIssue,
    SchemaIssue,
    UnsupportedRecordIssue,
)
from typeforge.pydantic._type_system import RuntimeType
from typeforge.utils.error_handling import safe_result


@safe_result(errors=(SchemaIssue,))
def emit_output(
    value: RuntimeType | s.RecordShape[RuntimeType] | s.RecordUnion[RuntimeType],
    handler: Callable[[object], CoreSchema],
    expression: object,
) -> CoreSchema:
    if isinstance(value, RuntimeType) and value.value is Never:
        raise SchemaIssue(
            "expected_type",
            "emission",
            expression,
            "Selected output Never has no values",
        )

    match value:
        case RuntimeType():
            annotation = value.annotation
        case s.RecordShape():
            annotation = _RecordAnnotation(value)
        case s.RecordUnion():
            annotation = _RecordUnionAnnotation(value)

    if isinstance(value, s.RecordShape | s.RecordUnion) and value.metadata:
        annotation = Annotated[
            annotation, *(item.annotation for item in value.metadata)
        ]

    try:
        # Continue the root annotation's middleware; fresh generation would
        # discard metadata Pydantic already removed from source_type for us.
        return handler(annotation)
    except PydanticSchemaGenerationError as error:
        raise SchemaIssue(
            "expected_type", "emission", expression, str(error)
        ) from error


@dataclass(frozen=True, slots=True)
class _RecordUnionAnnotation:
    records: s.RecordUnion[RuntimeType]

    def __get_pydantic_core_schema__(
        self, source: object, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.union_schema(
            [
                emit_output(record, handler.generate_schema, source).unwrap()
                for record in self.records.members
            ]
        )


@dataclass(frozen=True, slots=True)
class _RecordAnnotation:
    record: s.RecordShape[RuntimeType]

    def __get_pydantic_core_schema__(
        self, source: object, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        fields = {
            field.name: core_schema.typed_dict_field(
                handler.generate_schema(field.value.annotation),
                required=field.required,
                metadata={"pydantic_js_updates": {"readOnly": True}}
                if field.readonly
                else None,
            )
            for field in self.record.fields
        }
        # Schema's ordinary alias machinery owns references and build-local reuse.
        return core_schema.typed_dict_schema(
            fields, cls_name=self.record.name, total=False, extra_behavior="ignore"
        )


def emit_generic_failure(issue: MapNoMatchIssue | UnsupportedRecordIssue) -> CoreSchema:
    def reject(value: object) -> object:
        raise PydanticCustomError(
            "typeforge_unsupported_record"
            if isinstance(issue, UnsupportedRecordIssue)
            else "typeforge_map_no_match",
            "{message}",
            {"message": issue.render()},
        )

    return core_schema.no_info_plain_validator_function(
        reject,
        json_schema_input_schema=core_schema.any_schema(),
        metadata={"pydantic_js_updates": {"not": {}}},
    )
