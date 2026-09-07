import re
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from returns.result import Failure, Result, Success

from typeforge.analysis.model import (
    MappingKind,
    ReturnCheckProvenance,
    SourceMapping,
    SourcePosition,
    SourceSpan,
    VirtualDocument,
)
from typeforge.analysis.positions import source_position_from_utf8
from typeforge.compiler.emission import (
    EmissionError,
    emit_stub_module,
    emit_type_expression,
)
from typeforge.compiler.pipeline import (
    AdaptationError,
    AuthoredCallable,
    CompilationError,
    CompilationPlan,
    ImplicitReturnSite,
    LoweringError,
    RecordMaterializationError,
    SourceSyntaxError,
    VerificationPlan,
    compile_source,
    describe_authored_callables,
)
from typeforge.compiler.pipeline import SourceSpan as AuthoredSourceSpan
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    EachType,
    FixedTuple,
    FunctionDeclaration,
    HomogeneousTuple,
    MapType,
    MapValueType,
    OverloadDeclaration,
    Parameter,
    ParameterKind,
    StubModule,
    StubTypeExpression,
    TypeAliasDeclaration,
    TypeApplication,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    is_declaration,
    rewrite_type_children,
    union_types,
)
from typeforge.utils.error_handling import safe_result

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
    decorator_spans: tuple[AuthoredSourceSpan, ...]
    source_span: SourceSpan
    text: str


@dataclass(frozen=True, slots=True)
class _Edit:
    start: int
    end: int
    text: str
    authored_span: SourceSpan
    provenance: ReturnCheckProvenance | None = None


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
        return Failure(
            OverlayError(
                OverlayErrorCode.INVALID_ARITY,
                path,
                "maximum arity must be non-negative",
            )
        )

    if _START_MARKER in source:
        return Success(_identity_document(source, path, version))

    return Result.do(
        document
        for plan in compile_source(source, path, maximum_arity=maximum_arity).alt(
            lambda error: _compilation_error(path, error)
        )
        for document in project_overlay(plan, version=version)
    )


def project_overlay(
    plan: CompilationPlan,
    *,
    version: int = 0,
) -> Result[VirtualDocument, OverlayError]:
    return _project_overlay(plan, version=version).alt(
        lambda error: _emission_error(plan.source.path, error)
    )


@safe_result(errors=(EmissionError,))
def _project_overlay(plan: CompilationPlan, *, version: int) -> VirtualDocument:
    module = plan.source
    source = module.text
    path = module.path
    generated = _generate_overloads(source, plan)
    blocks = tuple(_overload_insertion(source, item) for item in generated)
    alias_edits = _alias_edits(source, plan)
    annotation_edits = _annotation_edits(source, plan)
    verification_edits = _verification_edits(
        source=source,
        plan=plan.verification,
        reserved_names={item.name for item in module.identifiers},
    )
    record_declarations = _render_derived_records(plan) if annotation_edits else ()
    content = (
        tuple(item.text for item in generated)
        + tuple(
            item.text
            for item in (
                *alias_edits,
                *annotation_edits,
                *verification_edits,
            )
        )
        + record_declarations
    )
    import_text = _typing_import(content, has_overloads=bool(generated))
    preamble = module.future_import_spans
    if module.docstring_span is not None:
        preamble = (module.docstring_span, *preamble)

    import_offset = _line_offset(source, preamble[-1].end.line) if preamble else 0
    import_anchor = _offset_span(path, source, import_offset, import_offset)
    import_edit = (
        (_Edit(import_offset, import_offset, import_text, import_anchor),)
        if import_text
        else ()
    )
    record_edit = (
        (
            _Edit(
                import_offset,
                import_offset,
                f"{'\n\n'.join(record_declarations)}\n\n",
                import_anchor,
            ),
        )
        if record_declarations
        else ()
    )
    edits = (
        *import_edit,
        *record_edit,
        *alias_edits,
        *annotation_edits,
        *blocks,
        *verification_edits,
    )
    if not edits:
        return _identity_document(
            source,
            path,
            version,
            authored_callables=describe_authored_callables(plan),
        )

    generated_text, mappings = _apply_edits(source, path, edits)
    return VirtualDocument(
        uri=path.resolve().as_uri() if path != Path("<memory>") else str(path),
        path=path,
        version=version,
        authored_text=source,
        generated_text=generated_text,
        mappings=mappings,
        authored_callables=describe_authored_callables(plan),
    )


def _generate_overloads(
    source: str,
    plan: CompilationPlan,
) -> tuple[_GeneratedOverloads, ...]:
    generated: list[_GeneratedOverloads] = []
    module = plan.source
    functions = {function.span: function for function in module.functions}
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
    for origin in plan.module.origins:
        declaration = origin.generated
        if not isinstance(declaration, OverloadDeclaration) or (
            declaration.decorator != "overload"
        ):
            # Record materialization's tf_typing.overload declarations belong to
            # published interfaces; overlays retain their authored implementations.
            continue

        function = functions.get(origin.origin)
        if function is None:
            continue

        declaration = _bound_structural_type_parameters(declaration, generic_classes)
        if _has_variadic_specializations(declaration):
            declaration = _positional_variadic_overloads(declaration)

        if _declaration_contains_map_value(declaration):
            continue

        declaration = replace(
            declaration,
            signatures=tuple(
                _checker_function(item) for item in declaration.signatures
            ),
            fallback=_checker_function(declaration.fallback),
        )
        emitted = emit_stub_module(
            StubModule(module.path.stem, (declaration,))
        ).unwrap()

        generated.append(
            _GeneratedOverloads(
                function.decorator_spans,
                _source_span(source, function.span),
                emitted.rstrip(),
            )
        )

    return tuple(generated)


def _checker_function(declaration: FunctionDeclaration) -> FunctionDeclaration:
    parameters = tuple(
        replace(parameter, annotation=_checker_type(parameter.annotation))
        for parameter in declaration.parameters
    )
    return replace(
        declaration,
        parameters=parameters,
        return_type=_checker_type(declaration.return_type),
    )


def _has_variadic_specializations(declaration: OverloadDeclaration) -> bool:
    if any(
        isinstance(parameter.annotation, EachType)
        for parameter in declaration.fallback.parameters
    ):
        return True

    return any(
        parameter.kind is ParameterKind.VAR_POSITIONAL
        for parameter in declaration.fallback.parameters
    ) and any(
        all(
            parameter.kind is not ParameterKind.VAR_POSITIONAL
            for parameter in signature.parameters
        )
        for signature in declaration.signatures
    )


def _declaration_contains_map_value(declaration: OverloadDeclaration) -> bool:
    return any(
        _function_contains_map_value(signature)
        for signature in (*declaration.signatures, declaration.fallback)
    )


def _function_contains_map_value(declaration: FunctionDeclaration) -> bool:
    return any(
        _type_contains_map_value(parameter.annotation)
        for parameter in declaration.parameters
    ) or _type_contains_map_value(declaration.return_type)


def _type_contains_map_value(expression: StubTypeExpression) -> bool:
    if isinstance(expression, MapValueType):
        return True

    if isinstance(expression, TypeApplication):
        return _type_contains_map_value(expression.constructor) or any(
            _type_contains_map_value(argument) for argument in expression.arguments
        )

    if isinstance(expression, FixedTuple):
        return any(_type_contains_map_value(item) for item in expression.items)

    if isinstance(expression, HomogeneousTuple | UnpackedType | EachType):
        return _type_contains_map_value(expression.item)

    if isinstance(expression, UnionExpression):
        return any(_type_contains_map_value(member) for member in expression.members)

    return False


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
    expression: StubTypeExpression,
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


def _source_span(source: str, span: AuthoredSourceSpan) -> SourceSpan:
    return SourceSpan(
        start=source_position_from_utf8(source, span.start.line - 1, span.start.column),
        end=source_position_from_utf8(source, span.end.line - 1, span.end.column),
    )


def _alias_edits(source: str, plan: CompilationPlan) -> tuple[_Edit, ...]:
    module = plan.source
    aliases = {alias.span: alias for alias in module.aliases}
    relationships = {
        origin.origin: origin.generated
        for origin in plan.module.origins
        if isinstance(origin.generated, MapType)
        and any(
            origin.generated is expression
            for expression in plan.module.reusable_elements
        )
    }
    edits: list[_Edit] = []
    for origin in plan.module.origins:
        declaration = origin.generated
        if not isinstance(declaration, TypeAliasDeclaration):
            continue

        alias = aliases[origin.origin]
        relationship = relationships.get(origin.origin)
        value = relationship if relationship is not None else declaration.value
        projected = replace(declaration, value=_checker_type(value))
        emitted = emit_stub_module(StubModule(module.path.stem, (projected,))).unwrap()

        span = _source_span(source, alias.span)
        edits.append(
            _Edit(
                start=span.start.offset,
                end=span.end.offset,
                text=emitted.rstrip(),
                authored_span=span,
            )
        )

    return tuple(edits)


def _annotation_edits(source: str, plan: CompilationPlan) -> tuple[_Edit, ...]:
    module = plan.source
    roots = {
        id(element): element
        for element in plan.module.reusable_elements
        if not is_declaration(element)
    }
    root_spans = tuple(
        origin.origin for origin in plan.module.origins if id(origin.generated) in roots
    )
    edits: list[_Edit] = []
    for origin in plan.module.origins:
        expression = roots.get(id(origin.generated))
        if expression is None or any(
            alias.span.start <= origin.origin.start
            and origin.origin.end <= alias.span.end
            for alias in module.aliases
        ):
            continue

        if any(
            span != origin.origin
            and span.start <= origin.origin.start
            and origin.origin.end <= span.end
            for span in root_spans
        ):
            continue

        emitted = emit_type_expression(_checker_type(expression)).unwrap()

        span = _source_span(source, origin.origin)
        edits.append(
            _Edit(
                span.start.offset,
                span.end.offset,
                emitted,
                span,
            )
        )

    return tuple(edits)


def _render_derived_records(
    plan: CompilationPlan,
) -> tuple[str, ...]:
    alias_spans = {alias.span for alias in plan.source.aliases}
    input_spans = {record.span for record in plan.source.typed_dicts}
    alias_records = {
        id(origin.generated)
        for origin in plan.module.origins
        if origin.origin in alias_spans
    }
    input_records = {
        id(origin.generated)
        for origin in plan.module.origins
        if origin.origin in input_spans
    }
    remaining_records = alias_records & input_records
    rendered: list[str] = []
    for declaration in plan.module.declarations:
        if (
            not isinstance(declaration, ClassDeclaration)
            or id(declaration) not in remaining_records
        ):
            continue

        remaining_records.remove(id(declaration))
        emitted = emit_stub_module(
            StubModule(plan.module.name, (declaration,))
        ).unwrap()
        rendered.append(emitted.rstrip())

    return tuple(rendered)


def _relationship_fallback(expression: MapType) -> StubTypeExpression:
    return union_types(
        (
            *(_checker_type(case.output_type) for case in expression.cases),
            _checker_type(expression.default),
        )
    )


def _checker_type(expression: StubTypeExpression) -> StubTypeExpression:
    if isinstance(expression, MapValueType):
        return TypeName("object")

    if isinstance(expression, MapType):
        return _relationship_fallback(expression)

    if isinstance(expression, UnionExpression):
        return union_types(tuple(_checker_type(item) for item in expression.members))

    return rewrite_type_children(expression, _checker_type)


def _verification_edits(
    source: str,
    plan: VerificationPlan,
    reserved_names: set[str],
) -> tuple[_Edit, ...]:
    reserved = set(reserved_names)
    next_identifier = 1
    edits: list[_Edit] = []
    for obligation in plan.obligations:
        site = obligation.site
        if isinstance(site, ImplicitReturnSite):
            end = source_position_from_utf8(
                source, site.suite.end.line - 1, site.suite.end.column
            )
            line_end = source.find("\n", end.offset)
            insertion_offset = len(source) if line_end < 0 else line_end + 1
            position = _offset_position(source, insertion_offset)
            expression_span = SourceSpan(position, position)
            expression_text = "None"
            indentation = " " * (obligation.function.span.start.column + 4)
            inline = False
            starts_line = True
            leading_newline = line_end < 0
        else:
            authored = site.expression or site.statement
            expression_span = SourceSpan(
                source_position_from_utf8(
                    source, authored.start.line - 1, authored.start.column
                ),
                source_position_from_utf8(
                    source, authored.end.line - 1, authored.end.column
                ),
            )
            expression_text = (
                source[expression_span.start.offset : expression_span.end.offset]
                if site.expression is not None
                else "None"
            )
            insertion_offset = source_position_from_utf8(
                source, site.statement.start.line - 1, site.statement.start.column
            ).offset
            line_start = source.rfind("\n", 0, insertion_offset) + 1
            prefix = source[line_start:insertion_offset]
            inline = bool(prefix.strip())
            indentation = "" if inline else prefix
            starts_line = False
            leading_newline = False

        assignments: list[str] = []
        expected_types: list[str] = []
        for expected in obligation.expected_types:
            emitted = emit_type_expression(expected)
            if isinstance(emitted, Failure):
                assignments = []
                break

            while True:
                name = f"__typeforge_return_{next_identifier}"
                next_identifier += 1
                if name not in reserved:
                    reserved.add(name)
                    break

            assignments.append(f"{name}: {emitted.unwrap()} = {expression_text}")
            expected_types.append(emitted.unwrap())

        if not assignments:
            continue

        text = _render_verification_assignments(
            assignments,
            indentation=indentation,
            inline=inline,
            starts_line=starts_line,
            leading_newline=leading_newline,
        )
        edits.append(
            _Edit(
                start=insertion_offset,
                end=insertion_offset,
                text=text,
                authored_span=expression_span,
                provenance=ReturnCheckProvenance(
                    callable_name=obligation.function.qualified_name,
                    return_annotation=(
                        obligation.function.returns.source
                        if obligation.function.returns is not None
                        else "Any"
                    ),
                    controller_parameter=obligation.contract.controller_parameter,
                    narrowed_inputs=tuple(
                        rendered
                        for expression in obligation.narrowed_inputs
                        if (rendered := emit_type_expression(expression).value_or(None))
                        is not None
                    ),
                    expected_types=tuple(expected_types),
                ),
            )
        )

    return tuple(edits)


def _render_verification_assignments(
    assignments: list[str],
    *,
    indentation: str,
    inline: bool,
    starts_line: bool,
    leading_newline: bool,
) -> str:
    if inline:
        return "; ".join(assignments) + "; "

    separator = f"\n{indentation}"
    rendered = separator.join(assignments)
    if starts_line:
        prefix = "\n" if leading_newline else ""
        return f"{prefix}{indentation}{rendered}\n"

    return f"{rendered}{separator}"


def _overload_insertion(
    source: str,
    generated: _GeneratedOverloads,
) -> _Edit:
    first_line = min(
        (span.start.line for span in generated.decorator_spans),
        default=generated.source_span.start.line + 1,
    )
    offset = _line_offset(source, first_line - 1)
    indentation = " " * generated.source_span.start.column
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


def _typing_import(content: tuple[str, ...], has_overloads: bool) -> str:
    combined = "\n".join(content)
    names = ["TYPE_CHECKING", "overload"] if has_overloads else []
    names.extend(
        name
        for name in ("Any", "Literal", "Never", "NotRequired", "ReadOnly", "TypedDict")
        if re.search(rf"(?<!tf_typing\.)\b{name}\b", combined)
    )
    imports = (
        *(("import typing as tf_typing",) if "tf_typing." in combined else ()),
        *((f"from typing import {', '.join(names)}",) if names else ()),
    )
    return "".join(f"{item}  {_IMPORT_MARKER}\n" for item in imports)


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
                edit.provenance,
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


def _identity_document(
    source: str,
    path: Path,
    version: int,
    authored_callables: tuple[AuthoredCallable, ...] = (),
) -> VirtualDocument:
    span = _offset_span(path, source, 0, len(source))
    return VirtualDocument(
        uri=path.resolve().as_uri() if path != Path("<memory>") else str(path),
        path=path,
        version=version,
        authored_text=source,
        generated_text=source,
        mappings=(_mapping(MappingKind.AUTHORED, span, span),),
        authored_callables=authored_callables,
    )


def _mapping(
    kind: MappingKind,
    authored: SourceSpan,
    generated: SourceSpan,
    provenance: ReturnCheckProvenance | None = None,
) -> SourceMapping:
    return SourceMapping(
        authored=authored,
        generated=generated,
        origin=kind,
        provenance=provenance,
    )


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


def _compilation_error(path: Path, error: CompilationError) -> OverlayError:
    match error:
        case SourceSyntaxError():
            return OverlayError(OverlayErrorCode.SYNTAX, error.path, error.message)
        case AdaptationError() | RecordMaterializationError():
            return _adaptation_error(path, error)
        case LoweringError():
            return OverlayError(OverlayErrorCode.LOWERING, path, error.message)


def _adaptation_error(
    path: Path,
    error: AdaptationError | RecordMaterializationError,
) -> OverlayError:
    return OverlayError(OverlayErrorCode.ADAPTATION, path, error.message)


def _emission_error(path: Path, error: EmissionError) -> OverlayError:
    return OverlayError(OverlayErrorCode.EMISSION, path, error.message)
