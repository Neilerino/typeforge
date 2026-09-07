"""Pydantic hook capabilities needed by the replacement, not a Map evaluator."""

from dataclasses import dataclass
from typing import Annotated, TypeVar, get_args

import pytest
from pydantic_core import CoreSchema, PydanticCustomError, core_schema

from pydantic import BaseModel, GetCoreSchemaHandler, ValidationError
from typeforge import Case, Map


def test_hook_preserves_generic_source_and_can_reject_unparametrized_use() -> None:
    sources: list[object] = []

    def reject(value: object) -> object:
        raise PydanticCustomError("typeforge_map_no_match", "No output for Any")

    @dataclass(frozen=True)
    class Observe:
        def __get_pydantic_core_schema__(
            self, source: object, handler: GetCoreSchemaHandler
        ) -> CoreSchema:
            sources.append(source)
            # Prove that the generic class can exist with an uninhabited field.
            # Selection and diagnostic policy belong to the future implementation.
            if isinstance(get_args(source)[0], TypeVar):
                return core_schema.no_info_plain_validator_function(
                    reject, json_schema_input_schema=core_schema.any_schema()
                )

            return handler.generate_schema(str)

    type Selected[T] = Map[T, Case[int, str]]

    class Payload[T](BaseModel):
        value: Annotated[Selected[T], Observe()]

    assert isinstance(get_args(sources[-1])[0], TypeVar)
    assert Payload[int].model_validate({"value": "3"}).value == "3"
    assert get_args(sources[-1]) == (int,)
    assert Payload[bytes].model_validate({"value": "3"}).value == "3"
    assert get_args(sources[-1]) == (bytes,)
    Payload[int].model_rebuild(force=True)
    assert get_args(sources[-1]) == (int,)

    with pytest.raises(ValidationError) as captured:
        Payload.model_validate({"value": "3"})

    assert captured.value.errors()[0]["loc"] == ("value",)
    assert captured.value.errors()[0]["type"] == "typeforge_map_no_match"
