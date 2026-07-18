import ast
import re
from dataclasses import dataclass
from pathlib import Path
from sys import executable

from returns.result import Failure, Result, Success

from typeforge.adapters.lsp import (
    LspConfiguration,
    LspDiagnostic,
    LspDocument,
    LspHover,
    LspPosition,
    LspRange,
    analyze_document,
)
from typeforge.analysis.mapping import (
    authored_to_generated,
    generated_span_to_authored,
    mapping_for_generated_offset,
)
from typeforge.analysis.model import (
    AnalysisRequest,
    AnalysisResult,
    CheckerCapabilities,
    CheckerError,
    Diagnostic,
    DiagnosticSeverity,
    HoverResult,
    MappingKind,
    SourcePosition,
    SourceSpan,
    VirtualDocument,
)
from typeforge.analysis.positions import source_position_from_utf16, utf16_character
from typeforge.diagnostics.filter import deduplicate_return_diagnostics
from typeforge.diagnostics.pyrefly import present_pyrefly_message
from typeforge.diagnostics.render import render_return_check

PYREFLY_COMMAND = (str(Path(executable).with_name("pyrefly")), "lsp")

PYREFLY_CAPABILITIES = CheckerCapabilities(
    diagnostics=True,
    hover=True,
    completion=False,
    signature_help=False,
    definitions=False,
    references=False,
    rename=False,
    code_actions=False,
    in_memory_documents=True,
)


@dataclass(frozen=True, slots=True)
class PyreflyAdapter:
    command: tuple[str, ...] = PYREFLY_COMMAND
    timeout_seconds: float = 15.0

    @property
    def name(self) -> str:
        return "pyrefly"

    @property
    def capabilities(self) -> CheckerCapabilities:
        return PYREFLY_CAPABILITIES

    def analyze(self, request: AnalysisRequest) -> Result[AnalysisResult, CheckerError]:
        document = request.document
        hover_positions = tuple(
            authored_to_generated(document, query.position)
            for query in request.hover_queries
        )
        lsp_result = analyze_document(
            LspConfiguration(
                command=(*self.command, *request.extra_arguments),
                root=request.project_root,
                initialization_options={
                    "pythonPath": executable,
                    "pyrefly": {
                        "typeCheckingMode": "strict",
                        "disableTypeErrors": False,
                        "analysis": {"showHoverGoToLinks": False},
                    },
                },
                timeout_seconds=self.timeout_seconds,
            ),
            LspDocument(
                uri=document.uri,
                text=document.generated_text,
                version=document.version,
            ),
            tuple(
                LspPosition(
                    item.line,
                    utf16_character(document.generated_text, item),
                )
                for item in hover_positions
            ),
        )
        if isinstance(lsp_result, Failure):
            lsp_error = lsp_result.failure()
            return Failure(
                CheckerError(
                    checker=self.name,
                    message="Pyrefly language server analysis failed",
                    detail=f"{lsp_error.code.value}: {lsp_error.message}",
                )
            )
        lsp_analysis = lsp_result.unwrap()
        diagnostics = tuple(
            normalize_diagnostic(document, item)
            for item in lsp_analysis.diagnostics
            if not is_overlay_artifact(document, item)
        )
        return Success(
            AnalysisResult(
                diagnostics=deduplicate_return_diagnostics(diagnostics),
                hovers=tuple(
                    normalized
                    for item in lsp_analysis.hovers
                    if (normalized := normalize_hover(document, item)) is not None
                ),
            )
        )


def is_overlay_artifact(document: VirtualDocument, diagnostic: LspDiagnostic) -> bool:
    if diagnostic.code == "unused-variable":
        generated = lsp_range_to_source_span(document.generated_text, diagnostic.range)
        mapping = mapping_for_generated_offset(
            document.mappings, generated.start.offset
        )
        if mapping is not None and mapping.origin is MappingKind.GENERATED:
            return True
    if diagnostic.code != "unused-import":
        return False
    match = re.fullmatch(r"Import `([^`]+)` is unused", diagnostic.message)
    if match is None:
        return False
    imported_name = match.group(1)
    pattern = rf"\b{re.escape(imported_name)}\b"
    if len(re.findall(pattern, document.authored_text)) <= len(
        re.findall(pattern, document.generated_text)
    ):
        return False
    try:
        tree = ast.parse(document.authored_text)
    except SyntaxError:
        return False
    return any(
        statement.module == "typeforge"
        and any(
            (alias.asname or alias.name) == imported_name for alias in statement.names
        )
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom)
    )


def normalize_diagnostic(
    document: VirtualDocument, diagnostic: LspDiagnostic
) -> Diagnostic:
    generated_span = lsp_range_to_source_span(document.generated_text, diagnostic.range)
    mapping = mapping_for_generated_offset(
        document.mappings, generated_span.start.offset
    )
    provenance = mapping.provenance if mapping is not None else None
    message = (
        render_return_check(provenance, diagnostic.message)
        if provenance is not None
        else present_pyrefly_message(
            document.authored_text,
            str(diagnostic.code) if diagnostic.code is not None else None,
            diagnostic.message,
        )
    )
    return Diagnostic(
        checker="pyrefly",
        path=document.path,
        span=generated_span_to_authored(document, generated_span),
        severity=normalize_severity(diagnostic.severity),
        message=message,
        code=str(diagnostic.code) if diagnostic.code is not None else None,
        provenance=provenance,
    )


def normalize_hover(document: VirtualDocument, hover: LspHover) -> HoverResult | None:
    if hover.contents is None:
        return None
    span = None
    if hover.range is not None:
        generated_span = lsp_range_to_source_span(document.generated_text, hover.range)
        span = generated_span_to_authored(document, generated_span)
    return HoverResult(
        checker="pyrefly",
        path=document.path,
        span=span,
        contents=hover.contents,
    )


def normalize_severity(value: int | None) -> DiagnosticSeverity:
    if value == 2:
        return DiagnosticSeverity.WARNING
    if value == 3:
        return DiagnosticSeverity.INFORMATION
    if value == 4:
        return DiagnosticSeverity.HINT
    return DiagnosticSeverity.ERROR


def lsp_range_to_source_span(source: str, range_: LspRange) -> SourceSpan:
    return SourceSpan(
        source_position(source, range_.start),
        source_position(source, range_.end),
    )


def source_position(source: str, position: LspPosition) -> SourcePosition:
    return source_position_from_utf16(source, position.line, position.character)
