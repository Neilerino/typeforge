from pathlib import Path

import libcst as cst
from libcst.metadata import QualifiedNameProvider


class ImportedMarkerCollector(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (QualifiedNameProvider,)

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: cst.Name) -> None:
        if node.value == "Each":
            qualified_names = self.get_metadata(QualifiedNameProvider, node, set())
            self.names.update(name.name for name in qualified_names)


def test_libcst_resolves_imported_marker_names() -> None:
    fixture = Path(__file__).parent / "fixtures" / "sample_package" / "__init__.py"
    module = cst.parse_module(fixture.read_text())
    collector = ImportedMarkerCollector()
    cst.MetadataWrapper(module).visit(collector)
    assert "typeforge.Each" in collector.names
