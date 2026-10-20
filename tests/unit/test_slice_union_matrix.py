"""Slice 02 evidence promoted to the public constructor in slice 08.

U01 through U31 retain the migration's behavioral witnesses; CONTEXT.md records the
union support boundaries and open decisions.
Expected semantic limitations remain characterizations, not fixes.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from subprocess import run
from sys import executable
from typing import TypeVar, get_args

import pytest
from returns.result import Failure

from pydantic import (
    BaseModel,
    PydanticSchemaGenerationError,
    TypeAdapter,
    ValidationError,
)
from typeforge import Is
from typeforge import Map as SliceMap
from typeforge import semantics as s
from typeforge._markers import Case
from typeforge._markers import Map as CanonicalMap
from typeforge.compiler.pipeline import generate_module
from typeforge.compiler.semantic_adapter import (
    COMPILER_TYPE_SYSTEM,
    NamedType,
    StaticType,
    lower_semantic_expression,
)
from typeforge.compiler.source import parse_source
from typeforge.overlay import transform_source
from typeforge.pydantic import Schema
from typeforge.pydantic._frontend import adapt_annotation

IMPORTS = """from typing import Annotated, Any, Literal, Never, TypeVar, TypedDict
from typeforge import Map, Value
from typeforge._markers import Equal, Assignable, All, Not
from typeforge._markers import Case, Default, Map as CanonicalMap
from typeforge import MapFields, Field, Key, Drop
from typeforge._markers import Any as AnyCondition
from typeforge.pydantic import Schema, Input
"""


@dataclass(frozen=True)
class UnionCase:
    name: str
    sliced: str
    canonical: str
    static_output: str | None
    runtime_output: str
    setup: str = ""
    runtime_error: str | None = None


CASES = (
    UnionCase(
        "U01-subject-distribution",
        "Map[int | str, int: bytes, str: float]",
        "CanonicalMap[int | str, Case[int, bytes], Case[str, float]]",
        "bytes | float",
        "bytes | float",
    ),
    UnionCase(
        "U02-subject-default",
        "Map[int | str, int: bytes, ...: float]",
        "CanonicalMap[int | str, Case[int, bytes], Default[float]]",
        "bytes | float",
        "bytes | float",
    ),
    UnionCase(
        "U03-subject-order",
        "Map[int | str, Assignable[object]: bytes, int: str, ...: float]",
        (
            "CanonicalMap[int | str, Case[Assignable[int | str, "
            "object], bytes], Case[int, str], Default[float]]"
        ),
        "bytes",
        "bytes",
    ),
    UnionCase(
        "U04-unmatched-member",
        "Map[int | str, int: bytes]",
        "CanonicalMap[int | str, Case[int, bytes]]",
        None,
        "bytes",
        runtime_error="map_no_match",
    ),
    UnionCase(
        "U05-union-selector-single-subject",
        "Map[int, int | str: bytes, ...: float]",
        "CanonicalMap[int, Case[int | str, bytes], Default[float]]",
        "bytes",
        "bytes",
    ),
    UnionCase(
        "U06-union-selector-union-subject",
        "Map[int | str, int | str: bytes, ...: float]",
        "CanonicalMap[int | str, Case[int | str, bytes], Default[float]]",
        "bytes",
        "bytes",
    ),
    UnionCase(
        "U07-equal-whole-subject",
        "Map[int | str, Equal[int]: bytes, ...: float]",
        "CanonicalMap[int | str, Case[Equal[int | str, int], bytes], Default[float]]",
        "float",
        "float",
    ),
    UnionCase(
        "U08-equal-whole-union",
        "Map[int | str, Equal[str | int]: bytes, ...: float]",
        (
            "CanonicalMap[int | str, Case[Equal[int | str, str | "
            "int], bytes], Default[float]]"
        ),
        "bytes",
        "bytes",
    ),
    UnionCase(
        "U09-assignable-union-target",
        "Map[int, Assignable[int | str]: bytes, ...: float]",
        "CanonicalMap[int, Case[Assignable[int, int | str], bytes], Default[float]]",
        "bytes",
        "bytes",
    ),
    UnionCase(
        "U10-assignable-all-subject-members",
        "Map[int | str, Assignable[int]: bytes, ...: float]",
        (
            "CanonicalMap[int | str, Case[Assignable[int | str, "
            "int], bytes], Default[float]]"
        ),
        "float",
        "float",
    ),
    UnionCase(
        "U11-compound-union-predicate",
        "Map[int, All[Assignable[int | str], Not[Equal[str]]]: bytes, ...: float]",
        (
            "CanonicalMap[int, Case[All[Assignable[int, int | str],"
            " Not[Equal[int, str]]], bytes], Default[float]]"
        ),
        "bytes",
        "bytes",
    ),
    UnionCase(
        "U12-union-output",
        "Map[int, int: str | None, ...: bytes]",
        "CanonicalMap[int, Case[int, str | None], Default[bytes]]",
        "str | None",
        "str | None",
    ),
    UnionCase(
        "U13-nested-union-output",
        "Map[int, int: list[str | None]]",
        "CanonicalMap[int, Case[int, list[str | None]]]",
        "list[str | None]",
        "list[str | None]",
    ),
    UnionCase(
        "U14-map-under-union",
        "Map[int, int: str, ...: bytes] | None",
        "CanonicalMap[int, Case[int, str], Default[bytes]] | None",
        "str | None",
        "str | None",
    ),
    UnionCase(
        "U15-map-under-nested-union",
        "list[Map[int, int: str] | None]",
        "list[CanonicalMap[int, Case[int, str]] | None]",
        "list[str | None]",
        "list[str | None]",
    ),
    UnionCase(
        "U16-alias-union-subject",
        "Map[Numbers, int: bytes, ...: float]",
        "CanonicalMap[Numbers, Case[int, bytes], Default[float]]",
        "bytes | float",
        "float",
        setup="type Numbers = int | str\n",
    ),
    UnionCase(
        "U17-alias-union-selector",
        "Map[int, Numbers: bytes, ...: float]",
        "CanonicalMap[int, Case[Numbers, bytes], Default[float]]",
        "bytes",
        "float",
        setup="type Numbers = int | str\n",
    ),
    UnionCase(
        "U18-alias-predicate-target",
        "Map[int, Assignable[Numbers]: bytes, ...: float]",
        "CanonicalMap[int, Case[Assignable[int, Numbers], bytes], Default[float]]",
        "bytes",
        "float",
        setup="type Numbers = int | str\n",
    ),
    UnionCase(
        "U19-captured-union-output",
        "Map[list[int | str], list[Value]: tuple[Value | None, ...]]",
        "CanonicalMap[list[int | str], Case[list[Value], tuple[Value | None, ...]]]",
        "tuple[int | str | None, ...]",
        "tuple[int | str | None, ...]",
    ),
    UnionCase(
        "U20-capture-drives-distribution",
        "Map[list[int | str], list[Value]: Map[Value, int: bytes, ...: float]]",
        (
            "CanonicalMap[list[int | str], Case[list[Value], "
            "CanonicalMap[Value, Case[int, bytes], "
            "Default[float]]]]"
        ),
        "bytes | float",
        "bytes | float",
    ),
    UnionCase(
        "U21-never-branch-with-valid-member",
        "Map[int | str, int: Never, ...: bytes]",
        "CanonicalMap[int | str, Case[int, Never], Default[bytes]]",
        "bytes",
        "bytes",
    ),
    UnionCase(
        "U22-never-under-output-union",
        "Map[int, int: Never] | str",
        "CanonicalMap[int, Case[int, Never]] | str",
        "str",
        "str",
    ),
    UnionCase(
        "U23-no-match-under-output-union",
        "Map[int, str: bytes] | float",
        "CanonicalMap[int, Case[str, bytes]] | float",
        None,
        "float",
        runtime_error="map_no_match",
    ),
    UnionCase(
        "U24-any-union-subject",
        "Map[Any | int, int: str, ...: bytes]",
        "CanonicalMap[Any | int, Case[int, str], Default[bytes]]",
        "str",
        "str",
    ),
    UnionCase(
        "U25-any-union-output",
        "Map[int, int: Any | str]",
        "CanonicalMap[int, Case[int, Any | str]]",
        "Any | str",
        "Any",
    ),
    UnionCase(
        "U26-input-union-bound",
        "Map[Input, int | str: bytes, ...: float]",
        "CanonicalMap[Input, Case[int | str, bytes], Default[float]]",
        "bytes | float",
        "object",
    ),
    UnionCase(
        "U27-distributed-deferred-bounds",
        "Map[int | str, int: Map[Input, int: bytes, ...: float], ...: bytes]",
        (
            "CanonicalMap[int | str, Case[int, CanonicalMap[Input, "
            "Case[int, bytes], Default[float]]], Default[bytes]]"
        ),
        "bytes | float",
        "object",
    ),
    UnionCase(
        "U28-annotated-union-output",
        'Map[int, int: Annotated[str | None, "description"]]',
        'CanonicalMap[int, Case[int, Annotated[str | None, "description"]]]',
        "str | None",
        "str | None",
    ),
    UnionCase(
        "U29-alias-whole-union-match",
        "Map[Numbers, Numbers: bytes, ...: float]",
        "CanonicalMap[Numbers, Case[Numbers, bytes], Default[float]]",
        "bytes",
        "bytes",
        setup="type Numbers = int | str\n",
    ),
    UnionCase(
        "U30-equal-same-order-union",
        "Map[int | str, Equal[int | str]: bytes, ...: float]",
        (
            "CanonicalMap[int | str, Case[Equal[int | str, int | "
            "str], bytes], Default[float]]"
        ),
        "bytes",
        "bytes",
    ),
    UnionCase(
        "U31-alias-union-output",
        "Map[int, int: Maybe[str]]",
        "CanonicalMap[int, Case[int, Maybe[str]]]",
        "str | None",
        "Maybe[str]",
        setup="type Maybe[T] = T | None\n",
    ),
)


def runtime_expression(expression: str, *, sliced: bool, setup: str = "") -> object:
    # These are fixed test fixtures, deliberately evaluated only for runtime tests.
    namespace: dict[str, object] = {"__name__": __name__}
    exec(IMPORTS, namespace)
    namespace["Map"] = SliceMap if sliced else CanonicalMap
    exec(setup, namespace)
    return eval(expression, namespace)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_union_static_schema_output(case: UnionCase, tmp_path: Path) -> None:
    path = tmp_path / "union_case.py"
    outputs: list[str] = []
    for expression in (case.sliced, case.canonical):
        path.write_text(
            IMPORTS + case.setup + "\nclass Payload:\n"
            f"    value: Schema[{expression}]\n"
        )
        result = generate_module(path, maximum_arity=2)
        if case.static_output is None:
            assert isinstance(result, Failure)
            assert "no case matched" in result.failure().message
            continue

        content = result.unwrap().content
        assert f"    value: {case.static_output}\n" in content, content
        outputs.append(content)

    if case.static_output is not None:
        assert outputs[0] == outputs[1]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_union_runtime_schema_output(case: UnionCase) -> None:
    # Both spellings must see the same authored alias identities.
    namespace: dict[str, object] = {"__name__": __name__}
    exec(IMPORTS, namespace)
    namespace["Map"] = CanonicalMap
    exec(case.setup, namespace)
    canonical: object = eval(case.canonical, namespace)
    namespace["Map"] = SliceMap
    sliced: object = eval(case.sliced, namespace)
    assert adapt_annotation(sliced).unwrap().expression == (
        adapt_annotation(canonical).unwrap().expression
    )

    if case.runtime_error is not None:
        for annotation in (sliced, canonical):
            with pytest.raises(PydanticSchemaGenerationError, match=case.runtime_error):
                TypeAdapter(Schema[annotation])

        return

    expected: object = eval(case.runtime_output, namespace)
    schema = TypeAdapter(expected).json_schema()
    if case.name == "U27-distributed-deferred-bounds":
        schema = {"anyOf": [{}, TypeAdapter(bytes).json_schema()]}

    assert TypeAdapter(Schema[sliced]).json_schema() == schema
    assert TypeAdapter(Schema[canonical]).json_schema() == schema


@pytest.mark.parametrize("sliced", [False, True])
def test_input_union_selection_validation_and_serialization(sliced: bool) -> None:
    annotation = runtime_expression(
        "Map[Input, int | str: int | None, str: str, ...: bool]"
        if sliced
        else (
            "CanonicalMap[Input, Case[int | str, int | None], "
            "Case[str, str], Default[bool]]"
        ),
        sliced=sliced,
    )
    adapter = TypeAdapter(Schema[annotation])
    for raw, expected in (("4", 4), (5, 5), (True, True)):
        value = adapter.validate_python(raw)
        assert value == expected and type(value) is type(expected)
        assert adapter.validate_json(adapter.dump_json(value)) == expected

    # str matches the first union selector. Neither the later str branch nor the
    # accepting bool fallback may rescue invalid output from that selected branch.
    with pytest.raises(ValidationError):
        adapter.validate_python("true")


@pytest.mark.parametrize("predicate", ["Equal", "Assignable"])
@pytest.mark.parametrize("sliced", [False, True])
def test_input_union_predicate_operands(predicate: str, sliced: bool) -> None:
    annotation = runtime_expression(
        f"Map[Input, {predicate}[int | str]: int, ...: bool]"
        if sliced
        else f"Map[Input, Case[{predicate}[Input, int | str], int], Default[bool]]",
        sliced=sliced,
    )
    adapter = TypeAdapter(Schema[annotation])
    if predicate == "Equal":
        with pytest.raises(ValidationError, match="bool_parsing"):
            adapter.validate_python("4")
    else:
        assert adapter.validate_python("4") == 4

    assert type(adapter.validate_python(True)) is (
        int if predicate == "Assignable" else bool
    )


def test_union_parameters_discover_substitute_and_rebuild() -> None:
    T = TypeVar("T")
    annotation = SliceMap[int, int : list[T | None]] | bytes
    canonical = CanonicalMap[int, Case[int, list[T | None]]] | bytes
    assert annotation == canonical
    # An outer union still traverses the already normalized branch arguments.
    assert get_args(annotation)[0].__parameters__ == (T,)
    selected = get_args(annotation)[0][str]
    assert selected == CanonicalMap[int, Case[int, list[str | None]]]
    assert TypeAdapter(Schema[selected]).validate_python(["x", None]) == ["x", None]

    type Output[T] = SliceMap[int, int : list[T | None]] | bytes

    class Payload[T](BaseModel):
        value: Schema[Output[T]]
        target: Schema[SliceMap[int, Is[T | str] : bytes, ... : list[T | None]]]

    specialized = Payload[int]
    for _ in range(2):
        model = specialized(value=["1", None], target=["2", None])
        assert model.value == [1, None]
        assert model.target == [2, None]
        assert specialized.model_validate_json(model.model_dump_json()).value == [
            1,
            None,
        ]
        specialized.model_rebuild(force=True)


@pytest.mark.parametrize(
    ("sliced", "canonical", "indeterminate"),
    [
        (
            "Map[int, int: str | bytes]",
            "CanonicalMap[int, Case[int, str | bytes]]",
            False,
        ),
        (
            "Map[T, int: str, ...: bytes]",
            "CanonicalMap[T, Case[int, str], Default[bytes]]",
            True,
        ),
        (
            "Map[T | int, int: str, ...: bytes]",
            "CanonicalMap[T | int, Case[int, str], Default[bytes]]",
            True,
        ),
        ("Map[T, int: str]", "CanonicalMap[T, Case[int, str]]", True),
    ],
)
def test_source_union_selection_retains_provenance(
    sliced: str,
    canonical: str,
    indeterminate: bool,
) -> None:
    results: list[s.EvaluationValue[StaticType]] = []
    unknown: s.UnresolvedType[StaticType] = s.UnresolvedType(
        NamedType("T"), s.TypeSymbol(("union_probe",), "T")
    )
    for expression in (sliced, canonical):
        source = (
            parse_source(IMPORTS + f"type Probe[T] = {expression}\n").unwrap().source
        )
        lowered = lower_semantic_expression(source.aliases[0].value, (("T", unknown),))
        result = s.evaluate(lowered, COMPILER_TYPE_SYSTEM).unwrap()
        assert (
            isinstance(result, s.IndeterminateType | s.UnresolvedType) is indeterminate
        )
        if indeterminate:
            if isinstance(result, s.IndeterminateType):
                assert len(result.alternatives) >= 2
            else:
                assert isinstance(result, s.UnresolvedType)
                assert isinstance(result.provenance, s.UnionTypeShape)
                assert any(
                    isinstance(member, s.IndeterminateType)
                    for member in result.provenance.members
                )

            comparison = s.EqualExpression(lowered, s.TypeReference(NamedType("str")))
            assert isinstance(
                s.evaluate(comparison, COMPILER_TYPE_SYSTEM).unwrap(),
                s.IndeterminateCondition,
            )

        results.append(result)

    assert results[0] == results[1]


@pytest.mark.parametrize("sliced", [False, True])
def test_selected_union_uses_pydantic_ambiguity_rules(sliced: bool) -> None:
    annotation = runtime_expression(
        "Map[Input, str: int | str, ...: bytes]"
        if sliced
        else "CanonicalMap[Input, Case[str, int | str], Default[bytes]]",
        sliced=sliced,
    )
    adapter = TypeAdapter(Schema[annotation])
    # Pydantic's smart union keeps a matching str instead of coercing it to int.
    value = adapter.validate_python("12")
    assert value == "12"
    assert adapter.dump_json(value) == b'"12"'


RECORD_SETUP = """\
class Row(TypedDict):
    value: int | str
    label: Literal["a"] | Literal["b"]
class Other(TypedDict):
    other: int
"""


@pytest.mark.parametrize("sliced", [False, True])
def test_union_field_values_through_existing_materialization(
    tmp_path: Path,
    sliced: bool,
) -> None:
    expression = (
        'MapFields[T, Map[Key, Literal["value"]: Field[Key, '
        "Map[Value, int: bytes, ...: float]], ...: Field[Key, Value]]]"
        if sliced
        else (
            'MapFields[T, CanonicalMap[Key, Case[Literal["value"], '
            "Field[Key, CanonicalMap[Value, Case[int, bytes], "
            "Default[float]]]], Default[Field[Key, Value]]]]"
        )
    )
    path = tmp_path / "fields.py"
    path.write_text(
        IMPORTS + RECORD_SETUP + f"type Mapped[T] = {expression}\n"
        "def f[T](x: T) -> Mapped[T]: ...\n"
    )
    content = generate_module(path, maximum_arity=2).unwrap().content
    record = content.split("class Mapped_Row", 1)[1].split("\n\n", 1)[0]
    assert "value: float" in record
    assert 'label: Literal["a"] | Literal["b"]' in record
    annotation = runtime_expression(
        expression.replace("[T,", "[Row,"), sliced=sliced, setup=RECORD_SETUP
    )
    adapter = TypeAdapter(Schema[annotation])
    assert adapter.json_schema()["properties"]["value"]["anyOf"] == [
        {"format": "binary", "type": "string"},
        {"type": "number"},
    ]
    assert adapter.validate_python({"value": b"x", "label": "a"}) == {
        "value": b"x",
        "label": "a",
    }


@pytest.mark.parametrize("sliced", [False, True])
def test_record_union_and_union_capture_patterns_remain_unsupported(
    tmp_path: Path,
    sliced: bool,
) -> None:
    record_expression = (
        "MapFields[Row | Other, Map[Key, ...: Field[Key, Value]]]"
        if sliced
        else "MapFields[Row | Other, CanonicalMap[Key, Default[Field[Key, Value]]]]"
    )
    capture_expression = (
        "Map[list[int], list[Value] | set[Value]: Value, ...: bytes]"
        if sliced
        else (
            "CanonicalMap[list[int], Case[list[Value] | set[Value],"
            " Value], Default[bytes]]"
        )
    )
    path = tmp_path / "unsupported.py"
    for expression, runtime_error, static_error in (
        (record_expression, "unsupported_record", "supported compiler record"),
        (capture_expression, "unbound_value", "Value requires"),
    ):
        body = (
            f"type Mapped[T] = {expression}\ndef f[T](x: T) -> Mapped[T]: ...\n"
            if expression == record_expression
            else f"class Payload:\n    value: Schema[{expression}]\n"
        )
        path.write_text(IMPORTS + RECORD_SETUP + body)
        result = generate_module(path, maximum_arity=2)
        assert isinstance(result, Failure)
        assert static_error in str(result.failure())
        annotation = runtime_expression(expression, sliced=sliced, setup=RECORD_SETUP)
        with pytest.raises(PydanticSchemaGenerationError, match=runtime_error):
            TypeAdapter(Schema[annotation])


@pytest.mark.parametrize("checker", ["mypy", "pyright", "pyrefly"])
@pytest.mark.parametrize("projection", ["overlay", "stub"])
def test_real_checkers_observe_union_callable_contracts(
    tmp_path: Path,
    checker: str,
    projection: str,
) -> None:
    source = """from typing import assert_type
from typeforge import Map
from typeforge._markers import Assignable, Equal
from typeforge._markers import Case, Default, Map as CanonicalMap
type Encoded[T] = Map[T, int: str | None, ...: bytes]
type Chosen[T] = Map[T, int | str: bytes, ...: float]
type Compatible[T] = Map[T, Assignable[int | str]: bytes, ...: float]
type Exact[T] = Map[T, Equal[int | str]: bytes, ...: float]
def encode[T](value: T) -> Encoded[T]:
    if type(value) is int:
        return str(value)
    return b"other"
def choose[T](value: T) -> Chosen[T]: raise NotImplementedError
def compatible[T](value: T) -> Compatible[T]: raise NotImplementedError
def exact[T](value: T) -> Exact[T]: raise NotImplementedError
"""
    consumer = """\
def inspect(value: int | str) -> None:
    assert_type(encode(1), str | None)
    assert_type(encode(value), str | None | bytes)
    assert_type(choose(value), bytes)
    assert_type(choose(1), bytes)
    assert_type(compatible(1), bytes)
    assert_type(exact(1), bytes)
"""
    canonical = (
        source.replace(
            "Map[T, int: str | None, ...: bytes]",
            "CanonicalMap[T, Case[int, str | None], Default[bytes]]",
        )
        .replace(
            "Map[T, int | str: bytes, ...: float]",
            "CanonicalMap[T, Case[int | str, bytes], Default[float]]",
        )
        .replace(
            "Map[T, Assignable[int | str]: bytes, ...: float]",
            "CanonicalMap[T, Case[Assignable[T, int | str], bytes], Default[float]]",
        )
        .replace(
            "Map[T, Equal[int | str]: bytes, ...: float]",
            "CanonicalMap[T, Case[Equal[T, int | str], bytes], Default[float]]",
        )
    )
    path = tmp_path / "library.py"
    if projection == "stub":
        outputs: list[str] = []
        for spelling in (source, canonical):
            path.write_text(spelling)
            outputs.append(generate_module(path, maximum_arity=2).unwrap().content)

        assert outputs[0] == outputs[1]
        path.with_suffix(".pyi").write_text(outputs[0])
        path = tmp_path / "consumer.py"
        path.write_text(
            "from typing import assert_type\n"
            "from library import encode, choose, compatible, exact\n" + consumer
        )
    else:
        sliced_overlay = transform_source(
            source + consumer, path, maximum_arity=2
        ).unwrap()
        canonical_overlay = transform_source(
            canonical + consumer, path, maximum_arity=2
        ).unwrap()
        assert sliced_overlay.generated_text == canonical_overlay.generated_text
        path.write_text(sliced_overlay.generated_text)

    command = [str(Path(executable).with_name(checker))]
    if checker == "mypy":
        command.extend(["--strict", "--no-incremental", "--follow-imports=silent"])
    elif checker == "pyright":
        config = tmp_path / "pyrightconfig.json"
        config.write_text(
            json.dumps(
                {
                    "pythonVersion": "3.14",
                    "typeCheckingMode": "standard",
                    "extraPaths": [str(Path("src").resolve())],
                }
            )
        )
        command.extend(["--project", str(config)])
    else:
        command.extend(
            [
                "check",
                "--config",
                str(Path("pyproject.toml").resolve()),
                "--python-interpreter-path",
                executable,
                "--search-path",
                str(tmp_path),
                "--search-path",
                str(Path("src").resolve()),
            ]
        )

    result = run([*command, str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    broken = path.read_text().replace("encode(1), str | None", "encode(1), bytes")
    path.write_text(broken)
    result = run([*command, str(path)], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "str" in result.stdout + result.stderr

    if projection == "overlay":
        broken_source = source.replace("return str(value)", "return 123")
        path.write_text(
            transform_source(broken_source, path, maximum_arity=2)
            .unwrap()
            .generated_text
        )
        result = run([*command, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode != 0
        assert "str" in result.stdout + result.stderr
