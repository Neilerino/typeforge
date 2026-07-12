import ast
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from typeforge._result import Err, Ok, Result
from typeforge.analysis.model import (
    MappingKind,
    SourceMapping,
    SourcePosition,
    SourceSpan,
    VirtualDocument,
)
from typeforge.compiler.emitter import emit_stub_module
from typeforge.compiler.frontend import SourceSyntaxError, parse_source
from typeforge.compiler.lowering import (
    ArityFrontier,
    EachType,
    FixedTuple,
    FunctionDeclaration,
    HomogeneousTuple,
    LoweringError,
    OverloadDeclaration,
    Parameter,
    ParameterKind,
    StubModule,
    TypeApplication,
    TypeExpression,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    lower_variadic_module,
)
from typeforge.compiler.model import (
    FunctionDeclaration as SourceFunction,
)
from typeforge.compiler.model import (
    SourceModule,
    contains_marker,
)
from typeforge.compiler.pipeline import (
    AdaptationError,
    adapt_alias,
    adapt_function,
    collect_semantic_map_aliases,
    expand_function_map_aliases,
)

_IMPORT_MARKER = "# typeforge: overlay-import"
_START_MARKER = "# typeforge: overlay"
_END_MARKER = "# typeforge: overlay-end"


class OverlayErrorCode(StrEnum):
    SYNTAX = "syntax"
    ADAPTATION = "adaptation"
    LOWERING = "lowering"
    EMISSION = "emission"
    INVALID_ARITY = "invalid_arity"


@dataclass(frozen=True, slots=True)
class OverlayError:
    code: OverlayErrorCode
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class _GeneratedOverloads:
    qualified_name: tuple[str, ...]
    source_span: SourceSpan
    text: str


@dataclass(frozen=True, slots=True)
class _Edit:
    start: int
    end: int
    text: str
    authored_span: SourceSpan


@dataclass(frozen=True, slots=True)
class _GenericClass:
    name: str
    parameters: tuple[tuple[str, str], ...]


def transform_source(
    source: str,
    path: Path = Path("<memory>"),
    maximum_arity: int = 8,
    version: int = 0,
) -> Result[VirtualDocument, OverlayError]:
    if maximum_arity < 0:
        return Err(
            OverlayError(
                OverlayErrorCode.INVALID_ARITY,
                path,
                "maximum arity must be non-negative",
            )
        )
    if _START_MARKER in source:
        return Ok(_identity_document(source, path, version))
    parsed = parse_source(source, path)
    if isinstance(parsed, Err):
        return Err(_frontend_error(parsed.error))
    generated = _generate_overloads(source, parsed.value, maximum_arity)
    if isinstance(generated, Err):
        return generated
    if not generated.value:
        return Ok(_identity_document(source, path, version))
    try:
        tree = ast.parse(source, filename=str(path), type_comments=True)
    except SyntaxError as error:
        return Err(OverlayError(OverlayErrorCode.SYNTAX, path, error.msg))
    nodes = _function_nodes(tree)
    blocks = tuple(
        _overload_insertion(source, item, nodes[item.qualified_name])
        for item in generated.value
        if item.qualified_name in nodes
    )
    import_text = _typing_import(tuple(item.text for item in generated.value))
    import_offset = _import_offset(source, tree)
    import_anchor = _offset_span(path, source, import_offset, import_offset)
    aliases = _alias_edits(source, parsed.value)
    if isinstance(aliases, Err):
        return aliases
    edits = (
        _Edit(import_offset, import_offset, import_text, import_anchor),
        *aliases.value,
        *blocks,
    )
    generated_text, mappings = _apply_edits(source, path, edits)
    return Ok(
        VirtualDocument(
            uri=path.resolve().as_uri() if path != Path("<memory>") else str(path),
            path=path,
            version=version,
            authored_text=source,
            generated_text=generated_text,
            mappings=mappings,
        )
    )


def _generate_overloads(
    source: str, module: SourceModule, maximum_arity: int
) -> Result[tuple[_GeneratedOverloads, ...], OverlayError]:
    aliases = collect_semantic_map_aliases(module.aliases)
    if isinstance(aliases, Err):
        return Err(_adaptation_error(module.path, aliases.error))
    generated: list[_GeneratedOverloads] = []
    class_parameters = {
        declaration.name: tuple(
            parameter.name for parameter in declaration.type_parameters
        )
        for declaration in module.classes
    }
    generic_classes = tuple(
        _GenericClass(
            declaration.name,
            tuple(
                (parameter.name, parameter.declaration)
                for parameter in declaration.type_parameters
            ),
        )
        for declaration in module.classes
        if declaration.type_parameters
    )
    for function in module.functions:
        enclosing = (
            class_parameters.get(function.qualified_name[0], ())
            if len(function.qualified_name) == 2
            else ()
        )
        adapted = adapt_function(function, enclosing)
        if isinstance(adapted, Err):
            return Err(_adaptation_error(module.path, adapted.error))
        expanded = expand_function_map_aliases(adapted.value, aliases.value)
        lowered = lower_variadic_module(
            StubModule(module.path.stem, (expanded,)),
            ArityFrontier(0, maximum_arity),
        )
        if isinstance(lowered, Err):
            return Err(_lowering_error(module.path, lowered.error))
        declaration = lowered.value.declarations[0]
        if not isinstance(declaration, OverloadDeclaration):
            continue
        declaration = _bound_structural_type_parameters(declaration, generic_classes)
        if any(
            isinstance(parameter.annotation, EachType)
            for parameter in expanded.parameters
        ):
            declaration = _positional_variadic_overloads(declaration)
        emitted = emit_stub_module(StubModule(module.path.stem, (declaration,)))
        if isinstance(emitted, Err):
            return Err(
                OverlayError(OverlayErrorCode.EMISSION, module.path, emitted.error)
            )
        generated.append(
            _GeneratedOverloads(
                function.qualified_name,
                _source_span(source, function),
                emitted.value.rstrip(),
            )
        )
    return Ok(tuple(generated))


def _bound_structural_type_parameters(
    declaration: OverloadDeclaration,
    classes: tuple[_GenericClass, ...],
) -> OverloadDeclaration:
    return OverloadDeclaration(
        signatures=tuple(
            _bound_signature_type_parameters(signature, classes)
            for signature in declaration.signatures
        ),
        fallback=declaration.fallback,
    )


def _bound_signature_type_parameters(
    signature: FunctionDeclaration,
    classes: tuple[_GenericClass, ...],
) -> FunctionDeclaration:
    bounds: dict[str, str] = {}
    for parameter in signature.parameters:
        _collect_structural_bounds(parameter.annotation, classes, bounds)
    _collect_structural_bounds(signature.return_type, classes, bounds)
    return FunctionDeclaration(
        name=signature.name,
        parameters=signature.parameters,
        return_type=signature.return_type,
        type_parameters=tuple(
            bounds.get(_type_parameter_name(parameter), parameter)
            for parameter in signature.type_parameters
        ),
        is_async=signature.is_async,
        decorators=signature.decorators,
    )


def _collect_structural_bounds(
    expression: TypeExpression,
    classes: tuple[_GenericClass, ...],
    bounds: dict[str, str],
) -> None:
    if isinstance(expression, TypeApplication):
        if isinstance(expression.constructor, TypeName):
            generic = next(
                (item for item in classes if item.name == expression.constructor.name),
                None,
            )
            if generic is not None:
                for argument, (formal_name, declaration) in zip(
                    expression.arguments, generic.parameters, strict=False
                ):
                    if (
                        isinstance(argument, TypeVariable)
                        and declaration != formal_name
                    ):
                        bounds.setdefault(
                            argument.name,
                            declaration.replace(formal_name, argument.name, 1),
                        )
        _collect_structural_bounds(expression.constructor, classes, bounds)
        for argument in expression.arguments:
            _collect_structural_bounds(argument, classes, bounds)
    elif isinstance(expression, FixedTuple):
        for item in expression.items:
            _collect_structural_bounds(item, classes, bounds)
    elif isinstance(expression, HomogeneousTuple):
        _collect_structural_bounds(expression.item, classes, bounds)
    elif isinstance(expression, UnionExpression):
        for member in expression.members:
            _collect_structural_bounds(member, classes, bounds)
    elif isinstance(expression, UnpackedType):
        _collect_structural_bounds(expression.item, classes, bounds)


def _type_parameter_name(declaration: str) -> str:
    return declaration.lstrip("*").split(":", 1)[0].split("=", 1)[0].strip()


def _positional_variadic_overloads(
    declaration: OverloadDeclaration,
) -> OverloadDeclaration:
    return OverloadDeclaration(
        signatures=tuple(
            FunctionDeclaration(
                name=signature.name,
                parameters=tuple(
                    Parameter(
                        name=parameter.name,
                        annotation=parameter.annotation,
                        kind=(
                            ParameterKind.POSITIONAL_ONLY
                            if parameter.kind is ParameterKind.POSITIONAL_OR_KEYWORD
                            else parameter.kind
                        ),
                        default=parameter.default,
                    )
                    for parameter in signature.parameters
                ),
                return_type=signature.return_type,
                type_parameters=signature.type_parameters,
                is_async=signature.is_async,
                decorators=signature.decorators,
            )
            for signature in declaration.signatures
        ),
        fallback=declaration.fallback,
    )


def _source_span(source: str, function: SourceFunction) -> SourceSpan:
    start_offset = _line_offset(source, function.span.start.line - 1) + (
        function.span.start.column
    )
    end_offset = _line_offset(source, function.span.end.line - 1) + (
        function.span.end.column
    )
    return SourceSpan(
        start=SourcePosition(
            offset=start_offset,
            line=function.span.start.line - 1,
            column=function.span.start.column,
        ),
        end=SourcePosition(
            offset=end_offset,
            line=function.span.end.line - 1,
            column=function.span.end.column,
        ),
    )


def _function_nodes(
    tree: ast.Module,
) -> dict[tuple[str, ...], ast.FunctionDef | ast.AsyncFunctionDef]:
    nodes: dict[tuple[str, ...], ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for statement in tree.body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            nodes[(statement.name,)] = statement
        elif isinstance(statement, ast.ClassDef):
            for member in statement.body:
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                    nodes[(statement.name, member.name)] = member
    return nodes


def _alias_edits(
    source: str, module: SourceModule
) -> Result[tuple[_Edit, ...], OverlayError]:
    edits: list[_Edit] = []
    for alias in module.aliases:
        if len(alias.qualified_name) != 1 or not contains_marker(alias.value):
            continue
        adapted = adapt_alias(alias)
        if isinstance(adapted, Err):
            return Err(_adaptation_error(module.path, adapted.error))
        emitted = emit_stub_module(StubModule(module.path.stem, (adapted.value,)))
        if isinstance(emitted, Err):
            return Err(
                OverlayError(OverlayErrorCode.EMISSION, module.path, emitted.error)
            )
        start = (
            _line_offset(source, alias.span.start.line - 1) + alias.span.start.column
        )
        end = _line_offset(source, alias.span.end.line - 1) + alias.span.end.column
        edits.append(
            _Edit(
                start=start,
                end=end,
                text=emitted.value.rstrip(),
                authored_span=_offset_span(module.path, source, start, end),
            )
        )
    return Ok(tuple(edits))


def _overload_insertion(
    source: str,
    generated: _GeneratedOverloads,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> _Edit:
    first_line = min(
        (decorator.lineno for decorator in node.decorator_list),
        default=node.lineno,
    )
    offset = _line_offset(source, first_line - 1)
    indentation = " " * node.col_offset
    member_indentation = f"{indentation}    "
    overloads = "\n".join(
        f"{member_indentation}{line}" if line else ""
        for line in generated.text.splitlines()
    )
    block = (
        f"{indentation}if TYPE_CHECKING:  {_START_MARKER}\n"
        f"{overloads}\n"
        f"{indentation}{_END_MARKER}\n"
    )
    return _Edit(offset, offset, block, generated.source_span)


def _typing_import(overloads: tuple[str, ...]) -> str:
    combined = "\n".join(overloads)
    names = ["TYPE_CHECKING", "overload"]
    names.extend(
        name
        for name in ("Any", "Literal", "Never")
        if re.search(rf"\b{name}\b", combined)
    )
    return f"from typing import {', '.join(names)}  {_IMPORT_MARKER}\n"


def _import_offset(source: str, tree: ast.Module) -> int:
    statements = tree.body
    index = 0
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        index = 1
    while index < len(statements):
        statement = statements[index]
        if not (
            isinstance(statement, ast.ImportFrom) and statement.module == "__future__"
        ):
            break
        index += 1
    if index == 0:
        return 0
    previous = statements[index - 1]
    return _line_offset(source, (previous.end_lineno or previous.lineno))


def _apply_edits(
    source: str, path: Path, edits: tuple[_Edit, ...]
) -> tuple[str, tuple[SourceMapping, ...]]:
    ordered = tuple(sorted(edits, key=lambda item: item.start))
    pieces: list[str] = []
    mappings: list[SourceMapping] = []
    authored_offset = 0
    generated_offset = 0
    for edit in ordered:
        unchanged = source[authored_offset : edit.start]
        pieces.append(unchanged)
        if unchanged:
            mappings.append(
                _mapping(
                    MappingKind.AUTHORED,
                    _offset_span(path, source, authored_offset, edit.start),
                    _offset_span(
                        path,
                        "".join(pieces),
                        generated_offset,
                        generated_offset + len(unchanged),
                    ),
                )
            )
        generated_offset += len(unchanged)
        pieces.append(edit.text)
        mappings.append(
            _mapping(
                MappingKind.GENERATED,
                edit.authored_span,
                _offset_span(
                    path,
                    "".join(pieces),
                    generated_offset,
                    generated_offset + len(edit.text),
                ),
            )
        )
        generated_offset += len(edit.text)
        authored_offset = edit.end
    tail = source[authored_offset:]
    pieces.append(tail)
    generated_text = "".join(pieces)
    if tail:
        mappings.append(
            _mapping(
                MappingKind.AUTHORED,
                _offset_span(path, source, authored_offset, len(source)),
                _offset_span(
                    path,
                    generated_text,
                    generated_offset,
                    len(generated_text),
                ),
            )
        )
    return generated_text, tuple(mappings)


def _identity_document(source: str, path: Path, version: int) -> VirtualDocument:
    span = _offset_span(path, source, 0, len(source))
    return VirtualDocument(
        uri=path.resolve().as_uri() if path != Path("<memory>") else str(path),
        path=path,
        version=version,
        authored_text=source,
        generated_text=source,
        mappings=(_mapping(MappingKind.AUTHORED, span, span),),
    )


def _mapping(
    kind: MappingKind, authored: SourceSpan, generated: SourceSpan
) -> SourceMapping:
    return SourceMapping(authored=authored, generated=generated, origin=kind)


def _offset_span(path: Path, source: str, start: int, end: int) -> SourceSpan:
    del path
    return SourceSpan(
        start=_offset_position(source, start),
        end=_offset_position(source, end),
    )


def _offset_position(source: str, offset: int) -> SourcePosition:
    prefix = source[:offset]
    line = prefix.count("\n")
    last_newline = prefix.rfind("\n")
    column = offset if last_newline < 0 else offset - last_newline - 1
    return SourcePosition(offset=offset, line=line, column=column)


def _line_offset(source: str, zero_based_line: int) -> int:
    if zero_based_line <= 0:
        return 0
    offset = 0
    for _ in range(zero_based_line):
        newline = source.find("\n", offset)
        if newline < 0:
            return len(source)
        offset = newline + 1
    return offset


def _frontend_error(error: SourceSyntaxError) -> OverlayError:
    return OverlayError(OverlayErrorCode.SYNTAX, error.path, error.message)


def _adaptation_error(path: Path, error: AdaptationError) -> OverlayError:
    return OverlayError(OverlayErrorCode.ADAPTATION, path, error.message)


def _lowering_error(path: Path, error: LoweringError) -> OverlayError:
    return OverlayError(OverlayErrorCode.LOWERING, path, error.message)
