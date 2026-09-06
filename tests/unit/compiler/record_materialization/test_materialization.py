from pathlib import Path

from returns.result import Failure

from typeforge.compiler.adaptation import adapt_source_module
from typeforge.compiler.record_materialization import (
    RecordMaterializationError,
    build_record_shapes,
    derive_record_shapes,
    materialize_record_transforms,
)
from typeforge.compiler.source import parse_module
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    ClassField,
    Import,
    TypeApplication,
    TypeName,
)


def test_materialization_preserves_typed_dict_field_order_and_modifiers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "records.py"
    path.write_text(
        "from typing import NotRequired, ReadOnly, TypedDict\n"
        "class Payload(TypedDict):\n"
        "    identifier: int\n"
        "    label: NotRequired[ReadOnly[str]]\n",
        encoding="utf-8",
    )
    source = parse_module(path).unwrap().source
    stub = adapt_source_module(source).unwrap()

    materialization = materialize_record_transforms(source, stub).unwrap()

    assert materialization.declarations == (
        ClassDeclaration(
            name="Payload",
            bases=(TypeName("tf_typing.TypedDict"),),
            fields=(
                ClassField(name="identifier", annotation=TypeName("int")),
                ClassField(
                    name="label",
                    annotation=TypeApplication(
                        constructor=TypeName("tf_typing.NotRequired"),
                        arguments=(
                            TypeApplication(
                                constructor=TypeName("tf_typing.ReadOnly"),
                                arguments=(TypeName("str"),),
                            ),
                        ),
                    ),
                ),
            ),
            methods=(),
        ),
    )
    assert materialization.imports == (Import("typing", "tf_typing"),)


def test_record_failures_are_owned_by_record_materialization(tmp_path: Path) -> None:
    path = tmp_path / "invalid_record_alias.py"
    path.write_text(
        "from typing import TypedDict\n"
        "from typeforge import Field, Key, MapFields, Value\n"
        "class Payload(TypedDict):\n"
        "    value: int\n"
        "type Copy = MapFields[Payload, Field[Key, Value]]\n",
        encoding="utf-8",
    )
    source = parse_module(path).unwrap().source

    result = derive_record_shapes(
        source.aliases,
        build_record_shapes(source.typed_dicts),
    )

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), RecordMaterializationError)
    assert result.failure().declaration == "Copy"
