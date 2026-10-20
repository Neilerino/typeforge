"""Named bindings through runtime evaluation and authored compiler inputs."""

from pathlib import Path
from subprocess import run
from sys import executable
from typing import get_args

import pytest
from returns.result import Failure

from pydantic import PydanticSchemaGenerationError, TypeAdapter
from typeforge import Map, type_function
from typeforge.compiler.pipeline import generate_module
from typeforge.pydantic import Schema


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "Map[tuple[int, int], tuple[Item, str]: bytes, Item: Item, ...: bool]",
            "tuple[int, int]",
        ),
        ("Map[int | str, int: bytes, Item: list[Item]]", "bytes | list[str]"),
        (
            "Map[list[int], list[Item]: Map[bytes, Other: tuple[Item, Other]]]",
            "tuple[int, bytes]",
        ),
    ],
)
def test_capture_scope_and_failed_attempt_isolation(
    tmp_path: Path, body: str, expected: str
) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Selected():\n"
        '    Item = Capture("Item")\n'
        '    Other = Capture("Other")\n'
        f"    return {body}\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    expected_type: object = eval(expected, namespace)
    assert (
        TypeAdapter(Schema[namespace["Selected"]]).json_schema()
        == TypeAdapter(expected_type).json_schema()
    )
    source = tmp_path / "scope.py"
    source.write_text(program + "class Payload:\n    value: Selected\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert generated.content.endswith(f"class Payload:\n    value: {expected}\n")


@pytest.mark.parametrize(
    "body",
    [
        "Map[int, int: Item, ...: bytes]",
        "Map[tuple[int, int], tuple[Item, str]: bytes, ...: Item]",
        "Map[list[int], list[Item]: Other, ...: bytes]",
    ],
)
def test_unbound_capture_errors_do_not_select_a_fallback(
    tmp_path: Path, body: str
) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Selected():\n"
        '    Item = Capture("Item")\n'
        '    Other = Capture("Item")\n'
        f"    return {body}\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    with pytest.raises(PydanticSchemaGenerationError, match="unbound_capture"):
        TypeAdapter(Schema[namespace["Selected"]])

    source = tmp_path / "unbound.py"
    source.write_text(program)
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    assert "capture 'Item' is unbound" in result.failure().message


def test_capture_template_constructs_once_and_keeps_parameter_identity() -> None:
    from typeforge import Capture

    constructions: list[object] = []

    @type_function
    def WrapOther[T]():
        Item = Capture("Item")
        constructions.append(Item)
        return Map[T, int:bytes, Item : tuple[Item, T]]

    annotation = WrapOther[int | str]
    assert (
        TypeAdapter(Schema[annotation]).json_schema()
        == TypeAdapter(bytes | tuple[str, int | str]).json_schema()
    )
    assert len(constructions) == 1
    assert WrapOther.__value__.__parameters__ == WrapOther.__type_params__
    token = constructions[0]
    symbol = get_args(token)[0]
    with pytest.raises(AttributeError):
        symbol.name = "Other"

    with pytest.raises(AttributeError):
        token.name = "Other"

    with pytest.raises(TypeError, match="truthiness"):
        bool(token)


def test_bound_capture_can_select_an_input_without_rebinding() -> None:
    from typeforge import Capture
    from typeforge.pydantic import Input

    Item = Capture("Item")
    adapter = TypeAdapter(
        Schema[Map[list[int], list[Item] : Map[Input, Item:float, ...:bytes]]]
    )
    assert adapter.validate_python(1) == 1.0
    assert adapter.validate_python("hello") == b"hello"


def test_bound_nested_capture_does_not_require_new_generic_arguments(
    tmp_path: Path,
) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def KnownShape[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[list[int], list[Item]: "
        "Map[T, list[Item]: str, ...: bytes]]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    for argument, output in (("list[int]", str), ("list[str]", bytes)):
        specialized: object = eval(f"KnownShape[{argument}]", namespace)
        assert (
            TypeAdapter(Schema[specialized]).json_schema()
            == TypeAdapter(output).json_schema()
        )

    source = tmp_path / "known_shape.py"
    source.write_text(program)
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "type KnownShape[T] = str | bytes" in generated.content


def test_module_capture_is_transparent_to_compiler_matching(tmp_path: Path) -> None:
    source = tmp_path / "module_token.py"
    source.write_text(
        "from typeforge import Capture, Map\n"
        "from typeforge.pydantic import Schema\n"
        'Item = Capture("Item")\n'
        "class Payload:\n"
        "    value: Schema[Map[list[int], list[Item]: Item]]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "Item: object" in generated.content
    assert "Item: Capture" not in generated.content
    assert generated.content.endswith("class Payload:\n    value: int\n")


@pytest.mark.parametrize(
    ("selector", "output", "message"),
    [
        (
            "tuple[Item, Other]",
            "tuple[Item, Other]",
            "one capture per structural branch",
        ),
        ("list[Item]", "Other", "unlowered type expression: CaptureType"),
    ],
)
def test_finite_callable_capture_frontier_does_not_alias_independent_tokens(
    tmp_path: Path, selector: str, output: str, message: str
) -> None:
    source = tmp_path / "callable_captures.py"
    source.write_text(
        "from typeforge import Capture, Collect, Each, Map\n"
        'Item = Capture("Item")\n'
        'Other = Capture("Item")\n'
        f"type Selected[T] = Map[T, {selector}: {output}, ...: T]\n"
        "def convert[T](*items: Each[T]) -> Collect[Selected[T]]: ...\n"
    )
    result = generate_module(source, maximum_arity=2)
    assert isinstance(result, Failure)
    assert message in result.failure().message


@pytest.mark.parametrize("name", ["", None, 1])
def test_capture_rejects_invalid_runtime_labels(name: object) -> None:
    from typeforge import Capture

    with pytest.raises(TypeError, match="nonempty string"):
        Capture(name)


@pytest.mark.parametrize(
    "declaration",
    [
        "Item = Capture(42)",
        'Item = Capture("")',
        'Item = Capture(name="Item")',
        'Item = Capture("Item", "Other")',
        'Item = Capture("Item"); Item = Capture("Item")',
        "Item = helper()",
    ],
)
def test_compiler_rejects_unsupported_declarations_at_authored_source(
    tmp_path: Path, declaration: str
) -> None:
    source = tmp_path / "invalid_capture.py"
    source.write_text(
        "from typeforge import Capture, type_function\n"
        "@type_function\n"
        "def Bad[T]():\n"
        f"    {declaration}\n"
        "    return T\n"
    )
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    issue = result.failure()
    assert issue.path == source
    assert issue.span.start.line == 4


def test_capture_diagnostics_use_public_spelling() -> None:
    from typeforge import Capture

    Item = Capture("Item")
    with pytest.raises(PydanticSchemaGenerationError) as raised:
        TypeAdapter(Schema[Map[int, int:Item]])

    assert "Capture" in str(raised.value)
    assert "CaptureSymbol" not in str(raised.value)


def test_structural_value_authoring_is_rejected_in_both_consumers(
    tmp_path: Path,
) -> None:
    from typeforge import Value

    with pytest.raises(PydanticSchemaGenerationError, match="Capture"):
        TypeAdapter(Schema[Map[list[int], list[Value] : set[Value]]])

    source = tmp_path / "old_capture.py"
    source.write_text(
        "from typeforge import Map, Value\n"
        "from typeforge.pydantic import Schema\n"
        "class Payload:\n"
        "    value: Schema[Map[list[int], list[Value]: set[Value]]]\n"
    )
    result = generate_module(source, maximum_arity=1)
    assert isinstance(result, Failure)
    assert "Capture" in result.failure().message


def test_independent_type_functions_keep_their_capture_scopes(tmp_path: Path) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Inner[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[T, Item: Item]\n"
        "@type_function\n"
        "def Outer[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[list[T], list[Item]: tuple[Item, Inner[str]]]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    annotation: object = eval("Outer[int]", namespace)
    assert (
        TypeAdapter(Schema[annotation]).json_schema()
        == TypeAdapter(tuple[int, str]).json_schema()
    )
    source = tmp_path / "scopes.py"
    source.write_text(program + "class Payload:\n    value: Outer[int]\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert generated.content.endswith("class Payload:\n    value: tuple[int, str]\n")


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
def test_named_capture_stubs_remain_checkable_by_existing_checkers(
    tmp_path: Path,
    checker: str,
) -> None:
    source = tmp_path / "captures.py"
    source.write_text(
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Pair[T]():\n"
        '    First = Capture("Item")\n'
        '    Second = Capture("Item")\n'
        "    return Map[T, tuple[First, Second]: tuple[Second, First], ...: bytes]\n"
        "class Payload:\n"
        "    value: Pair[tuple[int, str]]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap()
    (tmp_path / "captures.pyi").write_text(generated.content)
    (tmp_path / "pyrefly.toml").write_text(
        'python-version = "3.14"\nsearch-path = ["."]\n'
    )
    (tmp_path / "pyrightconfig.json").write_text(
        '{"pythonVersion": "3.14", "typeCheckingMode": "strict"}'
    )
    good = tmp_path / "good.py"
    good.write_text(
        "from typing import assert_type\nfrom captures import Payload\n"
        "def check(value: Payload) -> None:\n"
        "    assert_type(value.value, tuple[str, int])\n"
    )
    bad = tmp_path / "bad.py"
    bad.write_text(
        "from captures import Payload\n"
        "def check(value: Payload) -> None:\n"
        "    wrong: tuple[int, str] = value.value\n"
        "    print(wrong)\n"
    )
    commands = {
        "mypy": (executable, "-m", "mypy", "--strict", "--config-file", "/dev/null"),
        "pyright": (executable, "-m", "pyright", "--pythonpath", executable),
        "pyrefly": (str(Path(executable).with_name("pyrefly")), "check"),
    }
    accepted = run(
        (*commands[checker], str(good)), cwd=tmp_path, capture_output=True, text=True
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    rejected = run(
        (*commands[checker], str(bad)), cwd=tmp_path, capture_output=True, text=True
    )
    assert rejected.returncode != 0, rejected.stdout + rejected.stderr
    assert "tuple" in rejected.stdout + rejected.stderr


@pytest.mark.parametrize(
    ("subject", "selector", "output", "fallback", "expected"),
    [
        (
            "tuple[int, str]",
            "tuple[Item, Other]",
            "tuple[Other, Item]",
            "bytes",
            "tuple[str, int]",
        ),
        ("tuple[int, int]", "tuple[Item, Item]", "Item", "bytes", "int"),
        ("tuple[int, str]", "tuple[Item, Item]", "Item", "bytes", "bytes"),
        ("tuple[int, bool]", "tuple[Item, Item]", "Item", "bytes", "bytes"),
        (
            "tuple[int | str, str | int]",
            "tuple[Item, Item]",
            "Item",
            "bytes",
            "int | str",
        ),
        (
            "list[int]",
            "list[Item]",
            "Map[str, Item: bytes, ...: float]",
            "bytes",
            "float",
        ),
        (
            "list[str]",
            "list[Item]",
            "Map[str, Item: bytes, ...: float]",
            "bytes",
            "bytes",
        ),
    ],
)
def test_named_capture_patterns_in_both_consumers(
    tmp_path: Path,
    subject: str,
    selector: str,
    output: str,
    fallback: str,
    expected: str,
) -> None:
    program = (
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Selected():\n"
        '    Item = Capture("Item")\n'
        '    Other = Capture("Item")\n'
        f"    return Map[{subject}, {selector}: {output}, ...: {fallback}]\n"
    )
    namespace: dict[str, object] = {"__name__": __name__}
    exec(program, namespace)
    annotation = namespace["Selected"]
    expected_type: object = eval(expected, namespace)
    assert (
        TypeAdapter(Schema[annotation]).json_schema()
        == TypeAdapter(expected_type).json_schema()
    )
    source = tmp_path / "selected.py"
    source.write_text(program + "class Payload:\n    value: Selected\n")
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert f"type Selected = {expected}" in generated.content
    assert generated.content.endswith(f"class Payload:\n    value: {expected}\n")


def test_unknown_generic_capture_projects_a_bound_and_specializes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pair.py"
    source.write_text(
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def SamePair[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[T, tuple[Item, Item]: Item, ...: bytes]\n"
        "class Payload:\n"
        "    same: SamePair[tuple[int, int]]\n"
        "    mixed: SamePair[tuple[int, str]]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "type SamePair[T] = object" in generated.content
    assert generated.content.endswith(
        "class Payload:\n    same: int\n    mixed: bytes\n"
    )


def test_named_capture_reuses_a_discovered_argument() -> None:
    from typeforge import Capture

    @type_function
    def Element[T]():
        Item = Capture("Item")
        return Map[list[T], list[Item] : Item]

    assert TypeAdapter(Schema[Element[int]]).json_schema() == {"type": "integer"}
    assert TypeAdapter(Schema[Element[str]]).json_schema() == {"type": "string"}


def test_compiler_lowers_capture_declarations_without_execution(tmp_path: Path) -> None:
    source = tmp_path / "capture.py"
    source.write_text(
        "from typeforge import Capture, Map, type_function\n"
        "@type_function\n"
        "def Element[T]():\n"
        '    Item = Capture("Item")\n'
        "    return Map[list[T], list[Item]: Item]\n"
        "class Payload:\n"
        "    value: Element[int]\n"
    )
    generated = generate_module(source, maximum_arity=1).unwrap()
    assert "type Element[T] = T" in generated.content
    assert generated.content.endswith("class Payload:\n    value: int\n")
