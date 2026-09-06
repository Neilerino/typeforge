from pathlib import Path
from textwrap import dedent

from typeforge.compiler.pipeline import (
    AuthoredCallable,
    AuthoredParameter,
    AuthoredParameterKind,
    compile_source,
    describe_authored_callables,
)
from typeforge.overlay import transform_source


def test_descriptions_retain_authored_parameters_and_nested_names() -> None:
    source = dedent("""\
        from typeforge import Collect, Each

        class World:
            class Nested:
                def query[T](
                    self, first: str, /, limit: int = 1,
                    *components: Each[type[T]], enabled: bool = True,
                    **options: object,
                ) -> Collect[T]: ...

        def ordinary(value: int) -> int: ...
        """)
    plan = compile_source(source, Path("world.py"), maximum_arity=1).unwrap()

    descriptions = describe_authored_callables(plan)

    assert descriptions == (
        AuthoredCallable(
            qualified_name=("World", "Nested", "query"),
            parameters=(
                AuthoredParameter(
                    name="self",
                    kind=AuthoredParameterKind.POSITIONAL_ONLY,
                    annotation=None,
                    has_default=False,
                ),
                AuthoredParameter(
                    name="first",
                    kind=AuthoredParameterKind.POSITIONAL_ONLY,
                    annotation="str",
                    has_default=False,
                ),
                AuthoredParameter(
                    name="limit",
                    kind=AuthoredParameterKind.POSITIONAL_OR_KEYWORD,
                    annotation="int",
                    has_default=True,
                ),
                AuthoredParameter(
                    name="components",
                    kind=AuthoredParameterKind.VAR_POSITIONAL,
                    annotation="Each[type[T]]",
                    has_default=False,
                ),
                AuthoredParameter(
                    name="enabled",
                    kind=AuthoredParameterKind.KEYWORD_ONLY,
                    annotation="bool",
                    has_default=True,
                ),
                AuthoredParameter(
                    name="options",
                    kind=AuthoredParameterKind.VAR_KEYWORD,
                    annotation="object",
                    has_default=False,
                ),
            ),
            return_annotation="Collect[T]",
        ),
    )
    assert descriptions[0].display_name == "World.Nested.query"


def test_identity_overlay_keeps_descriptions_even_without_generated_edits() -> None:
    source = dedent("""\
        from typeforge import Value

        def read_context(value: Value): ...
        """)

    document = transform_source(source, maximum_arity=1).unwrap()

    assert document.generated_text == source
    assert document.authored_callables == (
        AuthoredCallable(
            qualified_name=("read_context",),
            parameters=(
                AuthoredParameter(
                    name="value",
                    kind=AuthoredParameterKind.POSITIONAL_OR_KEYWORD,
                    annotation="Value",
                    has_default=False,
                ),
            ),
            return_annotation=None,
        ),
    )


def test_alias_generated_overloads_do_not_broaden_diagnostic_selection() -> None:
    source = dedent("""\
        from typeforge import Map, Case, Default

        type Converted[T] = Map[T, Case[int, str], Default[bytes]]
        def convert[T](value: T) -> Converted[T]: ...
        """)
    plan = compile_source(source, Path("aliases.py"), maximum_arity=1).unwrap()

    assert describe_authored_callables(plan) == ()
