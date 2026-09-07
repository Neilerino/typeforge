"""Schema adaptation has one failure boundary and one static typing emitter."""

import ast
from pathlib import Path

import pytest

from .definitions import TYPE_FORGE


@pytest.fixture
def compiler_syntax() -> dict[Path, ast.Module]:
    return {
        path: ast.parse(path.read_text())
        for path in TYPE_FORGE.mod("compiler").path.rglob("*.py")
    }


def test_schema_semantic_failures_have_one_conversion_function(
    compiler_syntax: dict[Path, ast.Module],
) -> None:
    converters = {
        (path, function.name)
        for path, module in compiler_syntax.items()
        for function in ast.walk(module)
        if isinstance(function, ast.FunctionDef)
        and any(
            isinstance(node, ast.Name) and node.id == "SemanticIssue"
            for argument in function.args.args
            if argument.annotation is not None
            for node in ast.walk(argument.annotation)
        )
        and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "AdaptationError"
            for node in ast.walk(function)
        )
    }

    assert converters == {
        (
            TYPE_FORGE.file("compiler.adaptation._schema").path,
            "_schema_adaptation_error",
        )
    }


def test_static_type_emission_has_one_traversal(
    compiler_syntax: dict[Path, ast.Module],
) -> None:
    emitters = {
        (path, function.name)
        for path, module in compiler_syntax.items()
        for function in ast.walk(module)
        if isinstance(function, ast.FunctionDef)
        and {"NeverType", "ParameterizedType", "RecordShape"}
        <= {
            node.cls.id
            for node in ast.walk(function)
            if isinstance(node, ast.MatchClass) and isinstance(node.cls, ast.Name)
        }
        and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "TypeApplication"
            for node in ast.walk(function)
        )
    }

    assert emitters == {
        (
            TYPE_FORGE.file("compiler.semantic_adapter._emission").path,
            "static_type_expression",
        )
    }


def test_new_schema_adapter_is_not_yet_a_production_dependency(
    compiler_syntax: dict[Path, ast.Module],
) -> None:
    callers = {
        path
        for path, module in compiler_syntax.items()
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "adapt_schema_expression"
            for node in ast.walk(module)
        )
    }

    assert callers == set()
