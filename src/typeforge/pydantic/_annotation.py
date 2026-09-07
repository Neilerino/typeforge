"""Pydantic annotation hook for the public Schema alias."""

from dataclasses import dataclass
from typing import Annotated

from pydantic_core import CoreSchema
from returns.result import Failure

from pydantic import (
    GetCoreSchemaHandler,
    PydanticSchemaGenerationError,
    PydanticUndefinedAnnotation,
)
from typeforge.pydantic._compile import compile_annotation
from typeforge.pydantic._errors import UnresolvedAnnotationIssue


@dataclass(frozen=True, slots=True)
class _SchemaMetadata:
    def __get_pydantic_core_schema__(
        self, source_type: object, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        result = compile_annotation(source_type, handler)
        if isinstance(result, Failure):
            issue = result.failure()
            if isinstance(issue, UnresolvedAnnotationIssue):
                raise PydanticUndefinedAnnotation(issue.name, issue.message) from issue

            raise PydanticSchemaGenerationError(issue.render()) from issue

        return result.unwrap()


type Schema[T] = Annotated[T, _SchemaMetadata()]
