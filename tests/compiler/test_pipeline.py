from pathlib import Path

from returns.result import Failure, Success

from typeforge.compiler.pipeline import (
    AdaptationError,
    UnsupportedPublicDeclaration,
    generate_module,
)


def test_source_is_compiled_to_portable_overloads() -> None:
    path = Path(__file__).parent / "fixtures" / "pipeline.py"
    generated = generate_module(path, maximum_arity=2)
    assert isinstance(generated, Success)
    assert generated.unwrap().content == (
        "from external import Parser\n"
        "from typing import overload\n\n"
        "def identity[T](value: T) -> T: ...\n\n"
        "@overload\n"
        "def combine() -> Parser[tuple[()]]: ...\n"
        "@overload\n"
        "def combine[T1](parsers_1: Parser[T1], /) -> Parser[tuple[T1]]: ...\n"
        "@overload\n"
        "def combine[T1, T2](parsers_1: Parser[T1], "
        "parsers_2: Parser[T2], /) -> Parser[tuple[T1, T2]]: ...\n"
        "@overload\n"
        "def combine[T](*parsers: Parser[T]) -> Parser[tuple[T, ...]]: ...\n"
    )


def test_unpacked_collect_is_flattened_through_an_outer_union(tmp_path: Path) -> None:
    source = tmp_path / "query.py"
    source.write_text(
        "from typeforge import Collect, Each\n"
        "def query[E, *Ts]("
        "*components: Each[type[Ts]]"
        ") -> tuple[E, *Collect[Ts]] | None: ...\n",
        encoding="utf-8",
    )

    generated = generate_module(source, maximum_arity=2)

    assert isinstance(generated, Success)
    assert (
        "def query[E, Ts1, Ts2](components_1: type[Ts1], "
        "components_2: type[Ts2], /) -> tuple[E, Ts1, Ts2] | None: ..."
        in generated.unwrap().content
    )


def test_unsupported_public_statements_fail_instead_of_disappearing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsafe.py"
    source.write_text(
        "while ready():\n    serve()\n",
        encoding="utf-8",
    )
    generated = generate_module(source, maximum_arity=2)
    assert isinstance(generated, Failure)
    assert isinstance(generated.failure(), UnsupportedPublicDeclaration)
    assert generated.failure().line == 1


def test_nested_adaptation_failures_preserve_the_original_error(
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid_condition.py"
    source.write_text(
        "from typeforge import Equal, If\n"
        "def choose[T](value: T) -> If[Equal[T], str, bytes]: ...\n",
        encoding="utf-8",
    )

    generated = generate_module(source, maximum_arity=2)

    assert isinstance(generated, Failure)
    error = generated.failure()
    assert isinstance(error, AdaptationError)
    assert error.declaration == "choose"
    assert error.expression == "Equal[T]"
    assert error.message == "Equal requires two type arguments"


def test_classes_preserve_decorators_bounds_fields_and_lowered_methods(
    tmp_path: Path,
) -> None:
    source = tmp_path / "classes.py"
    source.write_text(
        "from dataclasses import dataclass\n"
        "from typing import Protocol\n"
        "from typeforge import Collect, Each\n"
        "class Entity(Protocol):\n"
        "    def __hash__(self) -> int: ...\n"
        "@dataclass(frozen=True)\n"
        "class World[E: Entity]:\n"
        "    entities: set[E]\n"
        "    @classmethod\n"
        "    def empty(cls) -> World[E]: ...\n"
        "    def bundle[*Ts](self, *values: Each[Ts]) -> Collect[Ts]: ...\n",
        encoding="utf-8",
    )

    generated = generate_module(source, maximum_arity=2)

    assert isinstance(generated, Success)
    assert (
        "@dataclass(frozen=True)\nclass World[E: Entity]:" in generated.unwrap().content
    )
    assert "    entities: set[E]" in generated.unwrap().content
    assert "    @classmethod\n    def empty(cls: Any) -> World[E]: ..." in (
        generated.unwrap().content
    )
    assert "    @overload\n    def bundle(self: Any) -> tuple[()]: ..." in (
        generated.unwrap().content
    )
    assert (
        "    def bundle[Ts1, Ts2](self: Any, values_1: Ts1, "
        "values_2: Ts2) -> tuple[Ts1, Ts2]: ..."
    ) in generated.unwrap().content
    assert (
        "    def bundle[*Ts](self: Any, *values: *Ts) -> tuple[*Ts]: ..."
    ) in generated.unwrap().content


def test_unsupported_class_body_declarations_fail(tmp_path: Path) -> None:
    source = tmp_path / "unsafe_class.py"
    source.write_text(
        "class Service:\n    public_value = make_value()\n",
        encoding="utf-8",
    )

    generated = generate_module(source, maximum_arity=2)

    assert isinstance(generated, Failure)
    assert isinstance(generated.failure(), UnsupportedPublicDeclaration)


def test_relative_imports_and_explicit_reexports_are_preserved(tmp_path: Path) -> None:
    source = tmp_path / "exports.py"
    source.write_text(
        "from .models import User\n"
        "from . import settings\n"
        '__all__ = ["User", "settings"]\n',
        encoding="utf-8",
    )
    generated = generate_module(source, maximum_arity=2)
    assert isinstance(generated, Success)
    assert generated.unwrap().content == (
        "from . import settings as settings\nfrom .models import User as User\n"
    )


def test_dynamic_exports_fail_instead_of_changing_the_public_api(
    tmp_path: Path,
) -> None:
    source = tmp_path / "exports.py"
    source.write_text("__all__ = make_exports()\n", encoding="utf-8")
    generated = generate_module(source, maximum_arity=2)
    assert isinstance(generated, Failure)
    assert isinstance(generated.failure(), UnsupportedPublicDeclaration)


def test_public_module_variables_are_preserved(tmp_path: Path) -> None:
    source = tmp_path / "variables.py"
    source.write_text(
        "from external import Service, make_service\n"
        "answer = 42\n"
        'labels = ["one", "two"]\n'
        "service = Service()\n"
        "dynamic = make_service()\n"
        "token: str\n"
        "legacy = None  # type: bytes | None\n"
        "left, right = (1, 'two')\n",
        encoding="utf-8",
    )
    generated = generate_module(source, maximum_arity=2)
    assert isinstance(generated, Success)
    assert generated.unwrap().content == (
        "from external import Service, make_service\n"
        "from typing import Any\n\n"
        "answer: int\n\n"
        "labels: list[str]\n\n"
        "service: Service\n\n"
        "dynamic: Any\n\n"
        "token: str\n\n"
        "legacy: bytes | None\n\n"
        "left: int\n\n"
        "right: str\n"
    )


def test_generated_declarations_share_one_ordered_emission_path(tmp_path: Path) -> None:
    source = tmp_path / "ordered.py"
    source.write_text(
        "from typing import TypedDict\n"
        "class User(TypedDict):\n"
        "    name: str\n"
        "value = 1\n"
        "def read() -> User: ...\n",
        encoding="utf-8",
    )

    generated = generate_module(source, maximum_arity=2)

    assert isinstance(generated, Success)
    content = generated.unwrap().content
    assert content.index("class User") < content.index("value: int")
    assert content.index("value: int") < content.index("def read")


def test_empty_typed_dict_uses_the_normal_class_body_emitter(tmp_path: Path) -> None:
    source = tmp_path / "empty_record.py"
    source.write_text(
        "from typing import TypedDict\nclass Empty(TypedDict):\n    pass\n",
        encoding="utf-8",
    )

    generated = generate_module(source, maximum_arity=2)

    assert isinstance(generated, Success)
    assert "class Empty(tf_typing.TypedDict):\n    pass" in generated.unwrap().content


def test_runtime_main_guard_is_ignored(tmp_path: Path) -> None:
    source = tmp_path / "application.py"
    source.write_text(
        "def run() -> None:\n"
        "    pass\n\n"
        'if __name__ == "__main__":\n'
        "    run()\n"
        "    debug_value = object()\n",
        encoding="utf-8",
    )
    generated = generate_module(source, maximum_arity=2)
    assert isinstance(generated, Success)
    assert generated.unwrap().content == "def run() -> None: ...\n"


def test_runtime_expression_statements_are_ignored(tmp_path: Path) -> None:
    source = tmp_path / "application.py"
    source.write_text(
        "service: Service\nservice.start()\n",
        encoding="utf-8",
    )
    generated = generate_module(source, maximum_arity=2)
    assert isinstance(generated, Success)
    assert generated.unwrap().content == "service: Service\n"


def test_assignment_expressions_that_bind_public_names_fail(tmp_path: Path) -> None:
    source = tmp_path / "application.py"
    source.write_text("(service := create_service())\n", encoding="utf-8")
    generated = generate_module(source, maximum_arity=2)
    assert isinstance(generated, Failure)
    assert isinstance(generated.failure(), UnsupportedPublicDeclaration)


def test_reversed_runtime_main_guard_is_ignored(tmp_path: Path) -> None:
    source = tmp_path / "application.py"
    source.write_text(
        'if "__main__" == __name__:\n    raise SystemExit\n',
        encoding="utf-8",
    )
    generated = generate_module(source, maximum_arity=2)
    assert isinstance(generated, Success)
    assert generated.unwrap().content == "\n"


def test_main_guard_else_branch_fails_instead_of_hiding_public_api(
    tmp_path: Path,
) -> None:
    source = tmp_path / "application.py"
    source.write_text(
        'if __name__ == "__main__":\n'
        "    raise SystemExit\n"
        "else:\n"
        "    imported_value = 1\n",
        encoding="utf-8",
    )
    generated = generate_module(source, maximum_arity=2)
    assert isinstance(generated, Failure)
    assert isinstance(generated.failure(), UnsupportedPublicDeclaration)
    assert generated.failure().line == 1


def test_schema_boundaries_resolve_in_model_fields_and_generated_stubs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models.py"
    source.write_text(
        "from pydantic import BaseModel\n"
        "from typing import TypedDict\n"
        "from typeforge import (\n"
        "    Case, Default, Equal, Field, If, Key, Map, MapFields, Value,\n"
        ")\n"
        "from typeforge.pydantic import Input, Schema\n\n"
        "type Wire[T] = Map[T, Case[bytes, str], Default[int]]\n\n"
        "class User(TypedDict):\n"
        "    name: str\n\n"
        "type Public[T] = MapFields[T, Field[Key, Value]]\n\n"
        "class Payload(BaseModel):\n"
        "    wire: Schema[Wire[bytes]]\n"
        "    direct: Schema[If[Equal[int, int], str, bytes]]\n"
        "    runtime: Schema[Map[Input, Case[int, int], Case[str, bytes]]]\n"
        "    runtime_if: Schema[If[Equal[Input, str], int, float]]\n"
        "    structural: Schema[Map["
        "list[int], Case[list[Value], Value], Default[bytes]]]\n"
        "    nested_capture: Schema[Map["
        "list[int], Case[list[Value], Map[Value, Case[int, str], Default[bytes]]], "
        "Default[float]]]\n"
        "    public: Schema[Public[User]]\n",
        encoding="utf-8",
    )

    generated = generate_module(source, maximum_arity=2)

    assert isinstance(generated, Success)
    content = generated.unwrap().content
    assert "from typeforge.pydantic import Schema" not in content
    assert "import typing as tf_typing" in content
    assert "class Public_User(tf_typing.TypedDict):\n    name: str" in content
    assert "    wire: str" in content
    assert "    direct: str" in content
    assert "    runtime: int | bytes" in content
    assert "    runtime_if: int | float" in content
    assert "    structural: int" in content
    assert "    nested_capture: str" in content
    assert "    public: Public_User" in content
