"""Data and modeled failures produced by record materialization."""

from dataclasses import dataclass

from typeforge.compiler.semantic_adapter import StaticType
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    ModuleImport,
    OverloadDeclaration,
)
from typeforge.semantics import RecordShape


@dataclass(frozen=True, slots=True)
class RecordMaterializationError(Exception):
    declaration: str
    expression: str
    message: str


@dataclass(frozen=True, slots=True)
class DerivedRecord:
    alias: str
    input_name: str
    shape: RecordShape[StaticType]


@dataclass(frozen=True, slots=True)
class RecordMaterialization:
    declarations: tuple[ClassDeclaration, ...]
    replacements: tuple[tuple[str, OverloadDeclaration], ...]
    imports: tuple[ModuleImport, ...]
    derived: tuple[DerivedRecord, ...] = ()
