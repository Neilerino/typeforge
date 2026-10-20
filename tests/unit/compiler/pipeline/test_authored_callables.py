from pathlib import Path
from textwrap import dedent

from returns.result import Failure

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


def test_unbound_field_value_cannot_publish_an_identity_overlay() -> None:
    source = dedent("""\
        from typeforge import Value

        def read_context(value: Value): ...
        """)

    result = transform_source(source, maximum_arity=1)
    assert isinstance(result, Failure)
    assert "declare Capture" in result.failure().message


def test_alias_generated_overloads_do_not_broaden_diagnostic_selection() -> None:
    source = dedent("""        from typeforge import Map

        type Converted[T] = Map[T, int : str, ... : bytes]
        def convert[T](value: T) -> Converted[T]: ...
        """)
    plan = compile_source(source, Path("aliases.py"), maximum_arity=1).unwrap()

    assert describe_authored_callables(plan) == ()
