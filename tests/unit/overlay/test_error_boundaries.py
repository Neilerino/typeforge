from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
from returns.result import Failure

from typeforge.compiler.emission import EmissionError
from typeforge.compiler.pipeline import compile_source
from typeforge.overlay import OverlayError, OverlayErrorCode, project_overlay


def test_emission_failure_is_translated_once_and_stops_later_declarations() -> None:
    source = dedent("""\
        from typeforge import Case, Map
        type First[T] = Map[T, Case[int, str]]
        type Second[T] = Map[T, Case[int, bytes]]
        """)
    path = Path("aliases.py")
    plan = compile_source(source, path, maximum_arity=1).unwrap()
    error = EmissionError("cannot render first alias")

    with patch(
        "typeforge.overlay.transform.emit_stub_module", return_value=Failure(error)
    ) as emit:
        result = project_overlay(plan)

    assert result == Failure(
        OverlayError(OverlayErrorCode.EMISSION, path, error.message)
    )
    assert emit.call_count == 1


def test_unexpected_emitter_exception_propagates_unchanged() -> None:
    source = dedent("""\
        from typeforge import Case, Map
        type Item[T] = Map[T, Case[int, str]]
        """)
    plan = compile_source(source, Path("alias.py"), maximum_arity=1).unwrap()
    error = RuntimeError("emitter bug")

    with (
        patch("typeforge.overlay.transform.emit_stub_module", side_effect=error),
        pytest.raises(RuntimeError) as raised,
    ):
        project_overlay(plan)

    assert raised.value is error


def test_unrenderable_verification_type_still_skips_only_the_obligation() -> None:
    source = dedent("""\
        from typeforge import Case, Map
        type Encoded[T] = Map[T, Case[int, str]]
        def convert[T](value: T) -> Encoded[T]:
            if type(value) is int:
                return value
            raise RuntimeError
        """)
    plan = compile_source(source, Path("convert.py"), maximum_arity=1).unwrap()
    assert len(plan.verification.obligations) == 1

    with patch(
        "typeforge.overlay.transform.emit_type_expression",
        return_value=Failure(EmissionError("cannot render check type")),
    ):
        document = project_overlay(plan).unwrap()

    assert "def convert(value: int) -> str: ..." in document.generated_text
    assert "__typeforge_return_" not in document.generated_text
    assert all(mapping.provenance is None for mapping in document.mappings)
