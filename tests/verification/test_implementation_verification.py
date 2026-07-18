import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest
from returns.result import Success

from typeforge.adapters.mypy import MypyAdapter
from typeforge.adapters.pyrefly import PyreflyAdapter
from typeforge.analysis import MappingKind
from typeforge.analysis.mapping import generated_to_authored, position_from_offset
from typeforge.analysis.model import AnalysisRequest
from typeforge.overlay import transform_source


@dataclass(frozen=True, slots=True)
class ReturnCheck:
    body: str
    expression: str
    expected: str


_PRELUDE = """
from typing import Literal, TypeGuard

from typeforge import Case, Default, Map


type Result[T] = Map[
    T,
    Case[int, str],
    Case[float, bool],
    Default[bytes],
]


def text() -> str:
    return "valid"


def flag() -> bool:
    return True


def binary() -> bytes:
    return b"valid"


class Values:
    text: str
    flag: bool
""".lstrip()


def _transform(body: str, path: Path = Path("verification.py")) -> str:
    source = f"{_PRELUDE}\n\n{dedent(body).strip()}\n"
    transformed = transform_source(source, path)
    assert isinstance(transformed, Success)
    ast.parse(transformed.unwrap().generated_text)
    return transformed.unwrap().generated_text


def _assert_return_check(generated: str, check: ReturnCheck) -> None:
    expected = re.escape(check.expected)
    expression = re.escape(check.expression)
    pattern = rf"(?m)[^#\n;]+:\s*{expected}\s*=\s*{expression}(?:\s*$|;)"
    assert re.search(pattern, generated), generated


@pytest.mark.parametrize(
    "check",
    (
        ReturnCheck(
            """
            def convert[T](value: T) -> Result[T]:
                if type(value) is int:
                    result = flag()
                    return result
                raise RuntimeError
            """,
            "result",
            "str",
        ),
        ReturnCheck(
            """
            def convert[T](value: T) -> Result[T]:
                if type(value) is int:
                    return flag()
                raise RuntimeError
            """,
            "flag()",
            "str",
        ),
        ReturnCheck(
            """
            def convert[T](value: T, values: Values) -> Result[T]:
                if type(value) is int:
                    return values.flag
                raise RuntimeError
            """,
            "values.flag",
            "str",
        ),
        ReturnCheck(
            """
            def convert[T](value: T, values: list[int]) -> Result[T]:
                if type(value) is int:
                    return [str(item) for item in values]
                raise RuntimeError
            """,
            "[str(item) for item in values]",
            "str",
        ),
        ReturnCheck(
            """
            def convert[T](value: T, enabled: bool) -> Result[T]:
                if type(value) is int:
                    return flag() if enabled else flag()
                raise RuntimeError
            """,
            "flag() if enabled else flag()",
            "str",
        ),
        ReturnCheck(
            """
            def convert[T](value: T) -> Result[T]:
                if type(value) is int:
                    return (lambda: False)()
                raise RuntimeError
            """,
            "(lambda: False)()",
            "str",
        ),
    ),
    ids=("name", "call", "attribute", "comprehension", "ternary", "lambda"),
)
def test_arbitrary_return_expressions_are_checked(check: ReturnCheck) -> None:
    generated = _transform(check.body)

    _assert_return_check(generated, check)


def test_awaited_return_expression_is_checked() -> None:
    body = """
    async def async_flag() -> bool:
        return True

    async def convert[T](value: T) -> Result[T]:
        if type(value) is int:
            return await async_flag()
        raise RuntimeError
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "await async_flag()", "str"))


def test_nested_flow_retains_the_outer_return_contract() -> None:
    body = """
    def convert[T](value: T, enabled: bool) -> Result[T]:
        if type(value) is int:
            if enabled:
                return flag()
            with open(__file__) as stream:
                for _ in stream:
                    try:
                        return flag()
                    except ValueError:
                        return flag()
                    finally:
                        enabled = False
            return flag()
        raise RuntimeError
    """

    generated = _transform(body)

    assert len(re.findall(r":\s*str\s*=\s*flag\(\)", generated)) == 4


def test_early_negative_guards_refine_the_remaining_path() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        if type(value) is not int:
            if type(value) is float:
                return flag()
            return binary()
        return text()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "flag()", "bool"))
    _assert_return_check(generated, ReturnCheck(body, "binary()", "bytes"))
    _assert_return_check(generated, ReturnCheck(body, "text()", "str"))


def test_compound_boolean_guards_produce_conjunctive_obligations() -> None:
    body = """
    def convert[T](value: T, enabled: bool) -> Result[T]:
        if type(value) is int and enabled:
            return text()
        if type(value) is int or type(value) is float:
            return flag()
        return binary()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "text()", "str"))
    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))
    _assert_return_check(generated, ReturnCheck(body, "flag()", "bool"))
    _assert_return_check(generated, ReturnCheck(body, "binary()", "bytes"))


def test_match_patterns_are_checked_against_remaining_cases() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        match value:
            case int():
                return text()
            case float():
                return flag()
            case _:
                return binary()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "text()", "str"))
    _assert_return_check(generated, ReturnCheck(body, "text()", "bytes"))
    _assert_return_check(generated, ReturnCheck(body, "flag()", "bool"))
    _assert_return_check(generated, ReturnCheck(body, "flag()", "bytes"))
    _assert_return_check(generated, ReturnCheck(body, "binary()", "bytes"))


def test_literal_none_and_or_patterns_are_supported() -> None:
    body = """
    type LiteralResult[T] = Map[
        T,
        Case[Literal["text"], str],
        Case[None, bytes],
        Default[bool],
    ]

    def convert[T](value: T) -> LiteralResult[T]:
        match value:
            case "text":
                return text()
            case None:
                return binary()
            case True | False:
                return flag()
            case _:
                return flag()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "text()", "str"))
    _assert_return_check(generated, ReturnCheck(body, "binary()", "bytes"))
    assert len(re.findall(r":\s*bool\s*=\s*flag\(\)", generated)) == 2


@pytest.mark.parametrize(
    "body",
    (
        """
        class Converter:
            @staticmethod
            def convert[T](value: T) -> Result[T]:
                if type(value) is int:
                    return flag()
                raise RuntimeError
        """,
        """
        class Converter:
            @classmethod
            def convert[T](cls, value: T) -> Result[T]:
                if type(value) is int:
                    return flag()
                raise RuntimeError
        """,
    ),
    ids=("staticmethod", "classmethod"),
)
def test_method_kinds_locate_the_controller_parameter(body: str) -> None:

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))


def test_instance_method_locates_controller_after_self() -> None:
    body = """
    class Converter:
        def convert[T](self, value: T) -> Result[T]:
            if type(value) is int:
                return flag()
            raise RuntimeError
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))


def test_nested_function_returns_are_not_rewritten_as_outer_returns() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        if type(value) is int:
            def inner() -> bool:
                return flag()
            return inner()
        raise RuntimeError
    """

    generated = _transform(body)

    assert not re.search(r":\s*str\s*=\s*flag\(\)", generated)
    _assert_return_check(generated, ReturnCheck(body, "inner()", "str"))


def test_generated_names_do_not_collide_with_authored_locals() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        __typeforge_return_1 = text()
        if type(value) is int:
            return flag()
        return binary()
    """

    generated = _transform(body)

    generated_names = re.findall(
        r"(?m)^\s*(__typeforge_return_\w+)\s*:\s*[^=]+\s*=", generated
    )
    assert generated_names
    assert "__typeforge_return_1" not in generated_names


def test_one_line_suites_remain_valid_and_are_verified() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        if type(value) is int: return flag()
        return binary()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))


def test_exact_overlapping_cases_are_kept_distinct() -> None:
    body = """
    type Overlap[T] = Map[
        T,
        Case[bool, bytes],
        Case[int, str],
        Default[float],
    ]

    def convert[T](value: T) -> Overlap[T]:
        if type(value) is bool:
            return binary()
        if type(value) is int:
            return text()
        return 1.0
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "binary()", "bytes"))
    _assert_return_check(generated, ReturnCheck(body, "text()", "str"))
    _assert_return_check(generated, ReturnCheck(body, "1.0", "float"))


def test_isinstance_accounts_for_subclasses_and_overlapping_cases() -> None:
    body = """
    type Overlap[T] = Map[
        T,
        Case[bool, bytes],
        Case[int, str],
        Default[float],
    ]

    def convert[T](value: T) -> Overlap[T]:
        if isinstance(value, int):
            return text()
        return 1.0
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "text()", "bytes"))
    _assert_return_check(generated, ReturnCheck(body, "text()", "str"))
    _assert_return_check(generated, ReturnCheck(body, "text()", "float"))


def test_isinstance_checks_the_original_no_default_example() -> None:
    body = """
    type Strict[T] = Map[
        T,
        Case[int, str],
        Case[float, bool],
    ]

    def convert[T](value: T) -> Strict[T]:
        if isinstance(value, int):
            return flag()
        if isinstance(value, float):
            return True
        return 42
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))
    _assert_return_check(generated, ReturnCheck(body, "True", "bool"))
    _assert_return_check(generated, ReturnCheck(body, "42", "Never"))


def test_default_can_preserve_the_controller_type() -> None:
    body = """
    type Preserved[T] = Map[T, Case[int, str], Default[T]]

    def convert[T](value: T) -> Preserved[T]:
        if type(value) is int:
            return text()
        return value
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "text()", "str"))
    _assert_return_check(generated, ReturnCheck(body, "value", "T"))


def test_missing_default_verifies_the_unhandled_path_as_never() -> None:
    body = """
    type Strict[T] = Map[T, Case[int, str]]

    def convert[T](value: T) -> Strict[T]:
        if type(value) is int:
            return text()
        return binary()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "binary()", "Never"))


def test_raise_and_noreturn_calls_need_no_return_obligation() -> None:
    body = """
    from typing import Never

    def fail() -> Never:
        raise RuntimeError

    def convert[T](value: T) -> Result[T]:
        if type(value) is int:
            raise RuntimeError
        fail()
    """

    generated = _transform(body)

    assert "__typeforge_return" not in generated


def test_bare_returns_are_checked_as_none() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        if type(value) is int:
            return
        raise RuntimeError
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "None", "str"))


def test_implicit_fallthrough_is_checked_as_none() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        if type(value) is int:
            return text()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "None", "bool"))
    _assert_return_check(generated, ReturnCheck(body, "None", "bytes"))


@pytest.mark.parametrize("body", ("pass", "..."))
def test_declaration_only_bodies_are_not_verified(body: str) -> None:
    generated = _transform(
        f"""
        def convert[T](value: T) -> Result[T]:
            {body}
        """
    )

    assert "__typeforge_return" not in generated


def test_assert_guards_refine_following_returns() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        assert type(value) is int
        return flag()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))


def test_nested_generators_do_not_disable_outer_verification() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        def values():
            yield 1

        if type(value) is int:
            return flag()
        return binary()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))


def test_generator_return_contracts_are_left_to_the_checker() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        yield value
        return flag()
    """

    generated = _transform(body)

    assert "__typeforge_return" not in generated


def test_unicode_before_return_uses_utf8_ast_offsets_safely() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        label = "é"
        if type(value) is int:
            return flag()
        return binary()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))


def test_exception_handlers_do_not_inherit_facts_from_the_try_body() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        try:
            if type(value) is int:
                return text()
            raise ValueError
        except ValueError:
            return flag()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "text()", "str"))
    assert not re.search(r":\s*str\s*=\s*flag\(\)", generated)


@pytest.mark.parametrize(
    "guard",
    (
        "is_int(value)",
        "narrowed",
        "type(alias) is int",
    ),
)
def test_unsupported_or_disconnected_guards_fall_back_to_aggregate(
    guard: str,
) -> None:
    body = f"""
    def is_int(value: object) -> TypeGuard[int]:
        return isinstance(value, int)

    def convert[T](value: T) -> Result[T]:
        narrowed = is_int(value)
        alias = value
        if {guard}:
            return flag()
        return binary()
    """

    generated = _transform(body)

    assert not re.search(r":\s*str\s*=\s*flag\(\)", generated)
    assert "type Result[T] = str | bool | bytes" in generated


def test_reassigned_controller_does_not_refine_the_original_type_parameter() -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        value = 1
        if type(value) is int:
            return flag()
        return binary()
    """

    generated = _transform(body)

    assert not re.search(r":\s*str\s*=\s*flag\(\)", generated)


def test_shared_type_variable_is_not_treated_as_one_controller() -> None:
    body = """
    def convert[T](value: T, other: T) -> Result[T]:
        if type(value) is int:
            return flag()
        return binary()
    """

    generated = _transform(body)

    assert not re.search(r":\s*str\s*=\s*flag\(\)", generated)


def test_direct_map_annotations_are_verified_without_an_alias() -> None:
    body = """
    def convert[T](value: T) -> Map[
        T,
        Case[int, str],
        Default[bytes],
    ]:
        if type(value) is int:
            return flag()
        return binary()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))


def test_structural_capture_returns_degrade_without_losing_the_overlay() -> None:
    body = """
    from typeforge import Value

    class Option[T]:
        value: T

    type Unwrapped[T] = Map[
        T,
        Case[Option[Value], Value],
        Default[T],
    ]

    def convert[T](value: T) -> Unwrapped[T]:
        if isinstance(value, Option):
            return value.value
        return value
    """

    generated = _transform(body)

    assert "type Unwrapped[T] = object | T" in generated
    assert "def convert" in generated
    assert "__typeforge_return" not in generated


def test_conditional_aliases_are_verified_inside_implementations() -> None:
    body = """
    from typeforge import Equal, If

    type Conditional[T] = If[Equal[T, int], str, bytes]

    def convert[T](value: T) -> Conditional[T]:
        if type(value) is int:
            return flag()
        return binary()
    """

    generated = _transform(body)

    assert "type Conditional[T] = str | bytes" in generated
    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))
    _assert_return_check(generated, ReturnCheck(body, "binary()", "bytes"))


def test_direct_conditional_annotations_are_verified() -> None:
    body = """
    from typeforge import Equal, If

    def convert[T](value: T) -> If[Equal[T, int], str, bytes]:
        if type(value) is int:
            return flag()
        return binary()
    """

    generated = _transform(body)

    _assert_return_check(generated, ReturnCheck(body, "flag()", "str"))


def test_generated_return_check_maps_back_to_the_authored_expression(
    tmp_path: Path,
) -> None:
    body = """
    def convert[T](value: T) -> Result[T]:
        if type(value) is int:
            return flag()
        raise RuntimeError
    """
    source = f"{_PRELUDE}\n\n{dedent(body).strip()}\n"
    path = tmp_path / "mapping.py"
    transformed = transform_source(source, path)
    assert isinstance(transformed, Success)
    document = transformed.unwrap()
    generated_expression = document.generated_text.index("= flag()") + 2
    authored_expression = source.index("flag()", source.index("def convert"))

    mapped = generated_to_authored(
        document,
        position_from_offset(document.generated_text, generated_expression),
    )

    assert mapped == position_from_offset(source, authored_expression)
    assert any(
        mapping.origin is MappingKind.GENERATED
        and mapping.authored.start.offset == authored_expression
        and mapping.provenance is not None
        and mapping.provenance.expected_types == ("str",)
        for mapping in document.mappings
    )


def test_pyrefly_checks_nonliteral_and_awaited_expressions_in_memory(
    tmp_path: Path,
) -> None:
    source = dedent(
        """
        from typeforge import Case, Default, Map

        type Result[T] = Map[T, Case[int, str], Default[bytes]]

        def flag() -> bool:
            return True

        def text() -> str:
            return "valid"

        async def async_flag() -> bool:
            return True

        def invalid_name[T](value: T) -> Result[T]:
            if type(value) is int:
                result = flag()
                return result
            return b"valid"

        def valid_call[T](value: T) -> Result[T]:
            if type(value) is int:
                return text()
            return b"valid"

        async def invalid_await[T](value: T) -> Result[T]:
            if type(value) is int:
                return await async_flag()
            return b"valid"
        """
    ).lstrip()
    path = tmp_path / "checker.py"
    path.write_text(source, encoding="utf-8")
    transformed = transform_source(source, path)
    assert isinstance(transformed, Success)
    pyrefly = Path(sys.executable).with_name("pyrefly")

    analyzed = PyreflyAdapter(
        command=(str(pyrefly), "lsp"), timeout_seconds=30.0
    ).analyze(AnalysisRequest(document=transformed.unwrap(), project_root=tmp_path))

    assert isinstance(analyzed, Success)
    invalid_name = source.index("result", source.index("return result"))
    invalid_await = source.index("await async_flag()")
    diagnostic_offsets = {
        diagnostic.span.start.offset for diagnostic in analyzed.unwrap().diagnostics
    }
    assert invalid_name in diagnostic_offsets
    assert invalid_await in diagnostic_offsets
    return_diagnostics = tuple(
        diagnostic
        for diagnostic in analyzed.unwrap().diagnostics
        if diagnostic.provenance is not None
    )
    assert len(return_diagnostics) == 2
    assert all(
        diagnostic.message.startswith("Invalid return from")
        for diagnostic in return_diagnostics
    )
    assert not any(
        source.index("text()", source.index("def valid_call"))
        == diagnostic.span.start.offset
        for diagnostic in analyzed.unwrap().diagnostics
    )


def test_mypy_checks_return_obligations_in_memory(tmp_path: Path) -> None:
    source = dedent(
        """
        from typeforge import Case, Default, Map

        type Result[T] = Map[T, Case[int, str], Default[bytes]]

        def flag() -> bool:
            return True

        def convert[T](value: T) -> Result[T]:
            if type(value) is int:
                return flag()
            return b"valid"
        """
    ).lstrip()
    path = tmp_path / "checker.py"
    path.write_text(source, encoding="utf-8")
    transformed = transform_source(source, path)
    assert isinstance(transformed, Success)

    analyzed = MypyAdapter().analyze(
        AnalysisRequest(document=transformed.unwrap(), project_root=tmp_path)
    )

    assert isinstance(analyzed, Success)
    return_diagnostics = tuple(
        item for item in analyzed.unwrap().diagnostics if item.provenance is not None
    )
    assert len(return_diagnostics) == 1
    assert return_diagnostics[0].span.start.offset == source.index(
        "flag()", source.index("def convert")
    )
    assert return_diagnostics[0].message.startswith("Invalid return from")


def test_original_map_implementation_example_reports_only_invalid_branches(
    tmp_path: Path,
) -> None:
    source = dedent(
        """
        from typeforge import Case, Map

        type TestMap[T] = Map[
            T,
            Case[int, str],
            Case[float, bool],
        ]

        def test_func[T](arg: T) -> TestMap[T]:
            if isinstance(arg, int):
                return True
            elif isinstance(arg, float):
                return True
            else:
                return 42
        """
    ).lstrip()
    path = tmp_path / "original.py"
    path.write_text(source, encoding="utf-8")
    transformed = transform_source(source, path)
    assert isinstance(transformed, Success)
    pyrefly = Path(sys.executable).with_name("pyrefly")

    analyzed = PyreflyAdapter(
        command=(str(pyrefly), "lsp"), timeout_seconds=30.0
    ).analyze(AnalysisRequest(document=transformed.unwrap(), project_root=tmp_path))

    assert isinstance(analyzed, Success)
    return_diagnostics = tuple(
        item for item in analyzed.unwrap().diagnostics if item.provenance is not None
    )
    assert len(return_diagnostics) == 2
    assert {
        item.provenance.expected_types
        for item in return_diagnostics
        if item.provenance is not None
    } == {
        ("str",),
        ("Never",),
    }
