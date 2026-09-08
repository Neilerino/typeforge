"""Failure short-circuiting at the runtime annotation compilation seam."""

from typing import Any

import pytest
from pydantic_core import CoreSchema
from returns.result import Failure

from pydantic import GetCoreSchemaHandler
from typeforge import Equal, Key, Map
from typeforge._markers import Case, Default
from typeforge._markers import Map as CanonicalMap
from typeforge.pydantic._compile import compile_annotation


class ForbiddenHandler(GetCoreSchemaHandler):
    def __call__(self, source_type: object, /) -> CoreSchema:
        raise AssertionError("Emission must not run after an earlier failure")


@pytest.mark.parametrize(
    ("expression", "phase", "code"),
    [
        (
            CanonicalMap[int, Default[str], Case[int, bytes]],
            "parsing",
            "invalid_marker",
        ),
        (Map[int, Equal[Key, Key] : str], "evaluation", "unbound_key"),
        (Map[Any, int:str], "evaluation", "map_no_match"),
        (Equal[int, int], "evaluation", "expected_type"),
    ],
)
def test_compilation_stops_before_emission_on_failed_stages(
    expression: object, phase: str, code: str
) -> None:
    result = compile_annotation(expression, ForbiddenHandler())

    assert isinstance(result, Failure)
    assert result.failure().phase == phase
    assert result.failure().code == code
