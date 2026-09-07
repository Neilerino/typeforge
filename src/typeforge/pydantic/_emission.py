"""Pydantic schemas for resolved types and uninhabited generic fallback fields."""

from typing import Never

from pydantic_core import CoreSchema, PydanticCustomError, core_schema
from returns.result import safe

from pydantic import GetCoreSchemaHandler, PydanticSchemaGenerationError
from typeforge.pydantic._errors import SchemaIssue
from typeforge.pydantic._type_system import RuntimeType


@safe(exceptions=(SchemaIssue,))
def emit_type(
    value: RuntimeType, handler: GetCoreSchemaHandler, expression: object
) -> CoreSchema:
    if value.value is Never:
        raise SchemaIssue(
            "expected_type",
            "emission",
            expression,
            "Selected output Never has no values",
        )

    try:
        # Continue the root annotation's middleware; fresh generation would
        # discard metadata Pydantic already removed from source_type for us.
        return handler(value.annotation)
    except PydanticSchemaGenerationError as error:
        raise SchemaIssue(
            "expected_type", "emission", expression, str(error)
        ) from error


def emit_no_match(issue: SchemaIssue) -> CoreSchema:
    def reject(value: object) -> object:
        raise PydanticCustomError(
            "typeforge_map_no_match", "{message}", {"message": issue.render()}
        )

    return core_schema.no_info_plain_validator_function(
        reject,
        json_schema_input_schema=core_schema.any_schema(),
        metadata={"pydantic_js_updates": {"not": {}}},
    )
