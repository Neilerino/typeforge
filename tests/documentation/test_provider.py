from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from typeforge._documentation import Doc
from typeforge._result import Err, Ok, Result
from typeforge.analysis.model import SourcePosition, VirtualDocument
from typeforge.documentation import (
    Documentation,
    DocumentationError,
    DocumentationErrorCode,
    DocumentationQuery,
    static_documentation,
)


def test_doc_is_an_inert_immutable_value() -> None:
    documentation = Doc("Useful documentation.")

    assert documentation.documentation == "Useful documentation."
    assert not hasattr(documentation, "__dict__")
    with pytest.raises(FrozenInstanceError):
        documentation.documentation = "Changed"  # type: ignore[misc]


def test_last_direct_doc_metadata_documents_a_local_alias(
    tmp_path: Path,
) -> None:
    source = """\
from typing import Annotated
from typeforge import Doc

type UserId = Annotated[
    int,
    Doc("Old documentation."),
    Doc("A stable user identifier.\\n\\n```python\\nuser_id: UserId\\n```"),
]

value: UserId
"""
    path = tmp_path / "src" / "models.py"
    result = _documentation_at(source, path, tmp_path, "UserId", occurrence=3)

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.markdown == (
        "A stable user identifier.\n\n```python\nuser_id: UserId\n```"
    )
    assert result.value.path == path
    assert result.value.span.start.line == 3


def test_nested_doc_does_not_override_direct_alias_documentation(
    tmp_path: Path,
) -> None:
    source = """\
from typing import Annotated
from typeforge import Doc

type Inner = Annotated[int, Doc("Inner documentation.")]
type Outer = Annotated[Inner, Doc("Outer documentation.")]
value: Outer
"""
    path = tmp_path / "src" / "models.py"

    result = _documentation_at(source, path, tmp_path, "Outer", occurrence=3)

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.markdown == "Outer documentation."


def test_nested_annotated_metadata_is_flattened_in_order(
    tmp_path: Path,
) -> None:
    source = """\
from typing import Annotated
from typeforge import Doc

type InnerWins = Annotated[Annotated[int, Doc("Inner.")], object()]
type OuterWins = Annotated[Annotated[int, Doc("Inner.")], Doc("Outer.")]
first: InnerWins
second: OuterWins
"""
    path = tmp_path / "src" / "models.py"

    inner = _documentation_at(source, path, tmp_path, "InnerWins", occurrence=2)
    outer = _documentation_at(source, path, tmp_path, "OuterWins", occurrence=2)

    assert isinstance(inner, Ok)
    assert inner.value is not None
    assert inner.value.markdown == "Inner."
    assert isinstance(outer, Ok)
    assert outer.value is not None
    assert outer.value.markdown == "Outer."


def test_documentation_does_not_transfer_to_an_undocumented_alias(
    tmp_path: Path,
) -> None:
    source = """\
from typing_extensions import Annotated, Doc

type Inner = Annotated[int, Doc("Shared documentation.")]
type Public = Inner
value: Public
"""
    path = tmp_path / "src" / "models.py"

    result = _documentation_at(source, path, tmp_path, "Public", occurrence=2)

    assert result == Ok(None)


def test_alias_documentation_does_not_transfer_to_a_field_name(
    tmp_path: Path,
) -> None:
    source = """\
from typing import Annotated
from typeforge import Doc

type Identifier = Annotated[int, Doc("An identifier.")]
identifier: Identifier
"""
    path = tmp_path / "src" / "models.py"

    field = _documentation_at(source, path, tmp_path, "identifier")
    annotation = _documentation_at(source, path, tmp_path, "Identifier", occurrence=2)

    assert field == Ok(None)
    assert isinstance(annotation, Ok)
    assert annotation.value is not None
    assert annotation.value.markdown == "An identifier."


def test_resolves_cross_file_relative_imports_and_re_exports(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    types_path = source_root / "library" / "types.py"
    public_path = source_root / "library" / "__init__.py"
    consumer_path = source_root / "consumer.py"
    types_source = """\
from typing import Annotated
from typeforge import Doc

raise RuntimeError("documentation lookup must not execute source")

type Identifier = Annotated[int, Doc("An imported identifier.")]
"""
    public_source = "from .types import Identifier as Identifier\n"
    consumer_source = "from library import Identifier\nvalue: Identifier\n"
    types_path.parent.mkdir(parents=True)
    types_path.write_text(types_source, encoding="utf-8")
    public_path.write_text(public_source, encoding="utf-8")

    result = _documentation_at(
        consumer_source,
        consumer_path,
        tmp_path,
        "Identifier",
        occurrence=2,
    )

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.markdown == "An imported identifier."
    assert result.value.path == types_path


def test_unsaved_workspace_document_takes_precedence_over_disk(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    types_path = source_root / "types.py"
    consumer_path = source_root / "consumer.py"
    disk_source = """\
from typing import Annotated
from typeforge import Doc
type Status = Annotated[str, Doc("Stale documentation.")]
"""
    buffered_source = disk_source.replace("Stale", "Unsaved")
    consumer_source = "from types import Status\nvalue: Status\n"
    types_path.parent.mkdir(parents=True)
    types_path.write_text(disk_source, encoding="utf-8")
    consumer = _document(consumer_path, consumer_source)
    buffered = _document(types_path, buffered_source)

    result = static_documentation(
        DocumentationQuery(
            document=consumer,
            position=_position(consumer_source, "Status", 2),
            project_root=tmp_path,
            workspace_documents=(buffered,),
        )
    )

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.markdown == "Unsaved documentation."


def test_configured_source_root_resolves_imported_documentation(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "library_source"
    types_path = source_root / "model_types.py"
    consumer_path = tmp_path / "consumer.py"
    types_path.parent.mkdir(parents=True)
    types_path.write_text(
        "from typing import Annotated\n"
        "from typeforge import Doc\n"
        'type Code = Annotated[str, Doc("A configured-root code.")]\n',
        encoding="utf-8",
    )
    consumer_source = "from model_types import Code\nvalue: Code\n"

    result = static_documentation(
        DocumentationQuery(
            document=_document(consumer_path, consumer_source),
            position=_position(consumer_source, "Code", 2),
            project_root=tmp_path,
            source_roots=(source_root,),
        )
    )

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.markdown == "A configured-root code."


def test_qualified_doc_and_annotated_names_are_supported(tmp_path: Path) -> None:
    source = """\
import typeforge as tf
import typing as t

type Amount = t.Annotated[int, tf.Doc(documentation="An amount.")]
value: Amount
"""
    path = tmp_path / "src" / "models.py"

    result = _documentation_at(source, path, tmp_path, "Amount", occurrence=2)

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.markdown == "An amount."


def test_qualified_type_reference_resolves_documentation(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    types_path = source_root / "model_types.py"
    consumer_path = source_root / "consumer.py"
    types_path.parent.mkdir(parents=True)
    types_path.write_text(
        "from typing import Annotated\n"
        "from typeforge import Doc\n"
        'type Code = Annotated[str, Doc("A qualified code.")]\n',
        encoding="utf-8",
    )
    source = "import model_types as mt\nvalue: mt.Code\n"

    result = _documentation_at(source, consumer_path, tmp_path, "Code")

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.markdown == "A qualified code."


def test_nested_qualified_type_reference_resolves_documentation(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    types_path = source_root / "library" / "model_types.py"
    consumer_path = source_root / "consumer.py"
    types_path.parent.mkdir(parents=True)
    types_path.write_text(
        "from typing import Annotated\n"
        "from typeforge import Doc\n"
        'type Code = Annotated[str, Doc("A nested qualified code.")]\n',
        encoding="utf-8",
    )
    source = "import library.model_types\nvalue: library.model_types.Code\n"

    result = _documentation_at(source, consumer_path, tmp_path, "Code")

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.markdown == "A nested qualified code."


def test_from_imported_module_reference_resolves_documentation(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    package = source_root / "models"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "types.py").write_text(
        "from typing import Annotated\n"
        "from typeforge import Doc\n"
        'type Code = Annotated[str, Doc("A module-qualified code.")]\n',
        encoding="utf-8",
    )
    source = "from models import types as model_types\nvalue: model_types.Code\n"

    result = _documentation_at(
        source,
        source_root / "consumer.py",
        tmp_path,
        "Code",
    )

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.markdown == "A module-qualified code."


def test_directly_annotated_fields_and_parameters_are_documented(
    tmp_path: Path,
) -> None:
    source = """\
from typing import Annotated
from typeforge import Doc

module_value: Annotated[int, Doc("A module value.")]

class Settings:
    enabled: Annotated[bool, Doc("Whether the feature is enabled.")]

def render(months: Annotated[int, Doc("The number of months.")]) -> None:
    pass
"""
    path = tmp_path / "src" / "models.py"

    module_value = _documentation_at(source, path, tmp_path, "module_value")
    field = _documentation_at(source, path, tmp_path, "enabled")
    parameter = _documentation_at(source, path, tmp_path, "months")

    assert isinstance(module_value, Ok)
    assert module_value.value is not None
    assert module_value.value.markdown == "A module value."
    assert isinstance(field, Ok)
    assert field.value is not None
    assert field.value.markdown == "Whether the feature is enabled."
    assert isinstance(parameter, Ok)
    assert parameter.value is not None
    assert parameter.value.markdown == "The number of months."


def test_documentation_markdown_is_cleaned_like_a_docstring(
    tmp_path: Path,
) -> None:
    source = '''\
from typing import Annotated
from typeforge import Doc

type Documented = Annotated[
    str,
    Doc(
        """
        A documented string.

        ```python
        value: Documented
        ```
        """
    ),
]
value: Documented
'''
    path = tmp_path / "src" / "models.py"

    result = _documentation_at(source, path, tmp_path, "Documented", occurrence=3)

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.markdown == (
        "A documented string.\n\n```python\nvalue: Documented\n```"
    )


def test_typeforge_marker_documentation_resolves_from_installed_source(
    tmp_path: Path,
) -> None:
    source = "from typeforge import Each\nvalue: Each[int]\n"
    path = tmp_path / "consumer.py"

    result = _documentation_at(source, path, tmp_path, "Each", occurrence=2)

    assert isinstance(result, Ok)
    assert result.value is not None
    assert "heterogeneous variadic parameter" in result.value.markdown


def test_invalid_doc_metadata_is_a_typed_failure(tmp_path: Path) -> None:
    source = """\
from typing import Annotated
from typeforge import Doc

message = "Dynamic"
type Label = Annotated[str, Doc(message)]
value: Label
"""
    path = tmp_path / "src" / "models.py"

    result = _documentation_at(source, path, tmp_path, "Label", occurrence=2)

    assert isinstance(result, Err)
    assert result.error.code is DocumentationErrorCode.INVALID_DOC
    assert result.error.path == path


def test_source_syntax_error_is_a_typed_failure(tmp_path: Path) -> None:
    source = "type Broken = Annotated[\n"
    path = tmp_path / "src" / "models.py"

    result = _documentation_at(source, path, tmp_path, "Broken")

    assert isinstance(result, Err)
    assert result.error.code is DocumentationErrorCode.SYNTAX


def test_non_type_symbol_has_no_documentation(tmp_path: Path) -> None:
    source = "value = 1\nprint(value)\n"
    path = tmp_path / "src" / "models.py"

    result = _documentation_at(source, path, tmp_path, "value", occurrence=2)

    assert result == Ok(None)


def _documentation_at(
    source: str,
    path: Path,
    project_root: Path,
    symbol: str,
    occurrence: int = 1,
) -> Result[Documentation | None, DocumentationError]:
    return static_documentation(
        DocumentationQuery(
            document=_document(path, source),
            position=_position(source, symbol, occurrence),
            project_root=project_root,
        )
    )


def _document(path: Path, source: str) -> VirtualDocument:
    return VirtualDocument(
        uri=path.resolve().as_uri(),
        path=path,
        version=1,
        authored_text=source,
        generated_text=source,
        mappings=(),
    )


def _position(source: str, symbol: str, occurrence: int) -> SourcePosition:
    offset = -1
    for _ in range(occurrence):
        offset = source.index(symbol, offset + 1)
    prefix = source[:offset]
    line = prefix.count("\n")
    line_start = prefix.rfind("\n") + 1
    return SourcePosition(offset, line, offset - line_start)
