from pathlib import Path
from textwrap import dedent

import pytest

from typeforge.compiler.adaptation import _source_to_ir, adapt_source_module
from typeforge.compiler.source import (
    ReturnSite,
    SourcePosition,
    SourceSpan,
    parse_source,
)
from typeforge.compiler.stub_ir import TypeName, UnionExpression
from typeforge.compiler.verification import ImplicitReturnSite, analyze_implementations


def test_guarded_return_uses_retained_contract_and_authored_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = parse_source(
        dedent("""\
            from typeforge import Case, Default, Map
            type Result[T] = Map[T, Case[int, str], Default[bytes]]
            def convert[T](value: T) -> Result[T]:
                if type(value) is int:
                    return value
                raise RuntimeError
            """),
        Path("convert.py"),
    ).unwrap()
    module = adapt_source_module(parsed.source).unwrap()

    def fail_readaptation(*args: object, **kwargs: object) -> None:
        pytest.fail("Implementation analysis must consume the retained contract")

    monkeypatch.setattr(_source_to_ir, "_adapt_function", fail_readaptation)
    monkeypatch.setattr(
        _source_to_ir, "_collect_semantic_relationship_aliases", fail_readaptation
    )
    monkeypatch.setattr(_source_to_ir, "expand_function_map_aliases", fail_readaptation)
    plan = analyze_implementations(parsed, module)

    assert len(plan.obligations) == 1
    obligation = plan.obligations[0]
    assert obligation.function is parsed.source.functions[0]
    assert obligation.contract.controller_parameter == "value"
    assert obligation.expected_types == (TypeName("str"),)
    assert obligation.narrowed_inputs == (TypeName("int"),)
    assert obligation.site == ReturnSite(
        statement=SourceSpan(
            Path("convert.py"), SourcePosition(5, 8), SourcePosition(5, 20)
        ),
        expression=SourceSpan(
            Path("convert.py"), SourcePosition(5, 15), SourcePosition(5, 20)
        ),
    )
    assert obligation.site is parsed.source.return_sites[0]


def test_bare_return_and_fallthrough_have_distinct_authored_sites() -> None:
    parsed = parse_source(
        dedent("""\
            from typeforge import Case, Default, Map
            def convert[T](value: T) -> Map[T, Case[int, str], Default[bytes]]:
                if type(value) is int:
                    return
                print(value)
            """),
        Path("convert.py"),
    ).unwrap()
    module = adapt_source_module(parsed.source).unwrap()

    explicit, implicit = analyze_implementations(parsed, module).obligations

    assert explicit.site == ReturnSite(
        statement=SourceSpan(
            Path("convert.py"), SourcePosition(4, 8), SourcePosition(4, 14)
        ),
        expression=None,
    )
    assert explicit.expected_types == (TypeName("str"),)
    assert implicit.site == ImplicitReturnSite(
        suite=SourceSpan(
            Path("convert.py"), SourcePosition(3, 4), SourcePosition(5, 16)
        ),
    )
    assert implicit.site.suite is parsed.source.functions[0].body_span
    assert implicit.expected_types == (TypeName("bytes"),)
    assert implicit.narrowed_inputs == ()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("yield value", id="generator"),
        pytest.param("...", id="declaration-only"),
    ],
)
def test_unsupported_bodies_have_no_invented_obligations(body: str) -> None:
    parsed = parse_source(
        "from typeforge import Case, Map\n"
        "def convert[T](value: T) -> Map[T, Case[int, str]]:\n"
        f"    {body}\n"
    ).unwrap()
    module = adapt_source_module(parsed.source).unwrap()

    assert analyze_implementations(parsed, module).obligations == ()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "if unknown(value):\n    return value\nraise RuntimeError",
            id="unknown-guard",
        ),
        pytest.param(
            "value = replacement\n"
            "if type(value) is int:\n    return value\nraise RuntimeError",
            id="controller-reassignment",
        ),
    ],
)
def test_unrecognized_flow_preserves_the_aggregate_check(body: str) -> None:
    indented_body = "\n".join(f"    {line}" for line in body.splitlines())
    parsed = parse_source(
        "from typeforge import Case, Default, Map\n"
        "def convert[T](value: T) -> Map[T, Case[int, str], Default[bytes]]:\n"
        f"{indented_body}\n"
    ).unwrap()
    module = adapt_source_module(parsed.source).unwrap()

    (obligation,) = analyze_implementations(parsed, module).obligations

    assert obligation.expected_types == (
        UnionExpression((TypeName("str"), TypeName("bytes"))),
    )
