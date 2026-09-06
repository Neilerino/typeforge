import ast
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
    LoweringError,
    RecordMaterializationError,
    SourceSyntaxError,
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
)
from typeforge.verification.contracts import union_types
from typeforge.verification.model import ReturnObligation, VerificationPlan
from typeforge.verification.planner import plan_implementation_verification

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

    compiled = compile_source(source, path, maximum_arity=maximum_arity)
    if isinstance(compiled, Failure):
        return Failure(_compilation_error(path, compiled.failure()))

    plan = compiled.unwrap()
    module = plan.source
    generated = _generate_overloads(source, plan)
    if isinstance(generated, Failure):
        return generated

    try:
        tree = ast.parse(source, filename=str(path), type_comments=True)
    except SyntaxError as error:
        return Failure(OverlayError(OverlayErrorCode.SYNTAX, path, error.msg))

    nodes = _function_nodes(tree)
    blocks = tuple(
        _overload_insertion(
            source,
            item,
            nodes[(item.qualified_name, item.source_span.start.line + 1)],
        )
        for item in generated.unwrap()
        if (item.qualified_name, item.source_span.start.line + 1) in nodes
    )
    alias_edits = _alias_edits(source, plan)
    if isinstance(alias_edits, Failure):
        return alias_edits

    schema_edits = _schema_edits(source, plan)
    if isinstance(schema_edits, Failure):
        return schema_edits

    verification = plan_implementation_verification(
        source,
        path,
        module,
        tree,
    )
    if isinstance(verification, Failure):
        return Failure(_adaptation_error(module.path, verification.failure()))

    verification_edits = _verification_edits(verification.unwrap())
    if isinstance(verification_edits, Failure):
        return Failure(
            OverlayError(
                OverlayErrorCode.EMISSION,
                path,
                verification_edits.failure(),
            )
        )

    records = _render_derived_records(plan) if schema_edits.unwrap() else Success(())
    if isinstance(records, Failure):
        return records

    record_declarations = records.unwrap()
    content = (
        tuple(item.text for item in generated.unwrap())
        + tuple(
            item.text
            for item in (
                *alias_edits.unwrap(),
                *schema_edits.unwrap(),
                *verification_edits.unwrap(),
            )
        )
        + record_declarations
    )
    import_text = _typing_import(content, has_overloads=bool(generated.unwrap()))
    import_offset = _import_offset(source, tree)
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
        *alias_edits.unwrap(),
        *schema_edits.unwrap(),
        *blocks,
        *verification_edits.unwrap(),
    )
    if not edits:
        return Success(
            _identity_document(
                source,
                path,
                version,
                authored_callables=describe_authored_callables(plan),
            )
        )

    generated_text, mappings = _apply_edits(source, path, edits)
    return Success(
        VirtualDocument(
            uri=path.resolve().as_uri() if path != Path("<memory>") else str(path),
            path=path,
            version=version,
            authored_text=source,
            generated_text=generated_text,
            mappings=mappings,
            authored_callables=describe_authored_callables(plan),
        )
    )


def _generate_overloads(
    source: str,
    plan: CompilationPlan,
) -> Result[tuple[_GeneratedOverloads, ...], OverlayError]:
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

        emitted = emit_stub_module(StubModule(module.path.stem, (declaration,)))
        if isinstance(emitted, Failure):
            return Failure(_emission_error(module.path, emitted.failure()))

        generated.append(
            _GeneratedOverloads(
                function.qualified_name,
                _source_span(source, function.span),
                emitted.unwrap().rstrip(),
            )
        )

    return Success(tuple(generated))


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
    start_offset = _line_offset(source, span.start.line - 1) + (span.start.column)
    end_offset = _line_offset(source, span.end.line - 1) + (span.end.column)
    return SourceSpan(
        start=SourcePosition(
            offset=start_offset,
            line=span.start.line - 1,
            column=span.start.column,
        ),
        end=SourcePosition(
            offset=end_offset,
            line=span.end.line - 1,
            column=span.end.column,
        ),
    )


def _function_nodes(
    tree: ast.Module,
) -> dict[tuple[tuple[str, ...], int], ast.FunctionDef | ast.AsyncFunctionDef]:
    nodes: dict[
        tuple[tuple[str, ...], int], ast.FunctionDef | ast.AsyncFunctionDef
    ] = {}

    def visit(statements: list[ast.stmt], scope: tuple[str, ...]) -> None:
        for statement in statements:
            if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
                nodes[((*scope, statement.name), statement.lineno)] = statement
            elif isinstance(statement, ast.ClassDef):
                visit(statement.body, (*scope, statement.name))
            elif isinstance(statement, ast.If | ast.While | ast.For | ast.AsyncFor):
                visit(statement.body, scope)
                visit(statement.orelse, scope)
            elif isinstance(statement, ast.Try | ast.TryStar):
                visit(statement.body, scope)
                for handler in statement.handlers:
                    visit(handler.body, scope)

                visit(statement.orelse, scope)
                visit(statement.finalbody, scope)
            elif isinstance(statement, ast.With | ast.AsyncWith):
                visit(statement.body, scope)
            elif isinstance(statement, ast.Match):
                for case in statement.cases:
                    visit(case.body, scope)

    visit(tree.body, ())
    return nodes


def _alias_edits(
    source: str, plan: CompilationPlan
) -> Result[tuple[_Edit, ...], OverlayError]:
    module = plan.source
    aliases = {alias.span: alias for alias in module.aliases}
    relationships = {
        origin.origin: origin.generated
        for origin in plan.module.origins
        if isinstance(origin.generated, MapType)
        and any(
            origin.generated is expression for expression in plan.module.expressions
        )
    }
    edits: list[_Edit] = []
    for origin in plan.module.origins:
        declaration = origin.generated
        if not isinstance(declaration, TypeAliasDeclaration):
            continue

        alias = aliases[origin.origin]
        relationship = relationships.get(origin.origin)
        projected = (
            replace(declaration, value=_relationship_fallback(relationship))
            if relationship is not None
            else declaration
        )
        emitted = emit_stub_module(StubModule(module.path.stem, (projected,)))
        if isinstance(emitted, Failure):
            return Failure(_emission_error(module.path, emitted.failure()))

        start = (
            _line_offset(source, alias.span.start.line - 1) + alias.span.start.column
        )
        end = _line_offset(source, alias.span.end.line - 1) + alias.span.end.column
        edits.append(
            _Edit(
                start=start,
                end=end,
                text=emitted.unwrap().rstrip(),
                authored_span=_offset_span(module.path, source, start, end),
            )
        )

    return Success(tuple(edits))


def _schema_edits(
    source: str, plan: CompilationPlan
) -> Result[tuple[_Edit, ...], OverlayError]:
    module = plan.source
    roots = {id(expression): expression for expression in plan.module.expressions}
    edits: list[_Edit] = []
    for origin in plan.module.origins:
        expression = roots.get(id(origin.generated))
        if expression is None or any(
            alias.span.start <= origin.origin.start
            and origin.origin.end <= alias.span.end
            for alias in module.aliases
        ):
            continue

        emitted = emit_type_expression(expression)
        if isinstance(emitted, Failure):
            return Failure(_emission_error(module.path, emitted.failure()))

        span = origin.origin
        start = _line_offset(source, span.start.line - 1) + span.start.column
        end = _line_offset(source, span.end.line - 1) + span.end.column
        edits.append(
            _Edit(
                start,
                end,
                emitted.unwrap(),
                _offset_span(module.path, source, start, end),
            )
        )

    return Success(tuple(edits))


def _render_derived_records(
    plan: CompilationPlan,
) -> Result[tuple[str, ...], OverlayError]:
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
        emitted = emit_stub_module(StubModule(plan.module.name, (declaration,)))
        if isinstance(emitted, Failure):
            return Failure(_emission_error(plan.source.path, emitted.failure()))

        rendered.append(emitted.unwrap().rstrip())

    return Success(tuple(rendered))


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

    if isinstance(expression, TypeApplication):
        return TypeApplication(
            _checker_type(expression.constructor),
            tuple(_checker_type(item) for item in expression.arguments),
        )

    if isinstance(expression, UnionExpression):
        return union_types(tuple(_checker_type(item) for item in expression.members))

    return expression


def _verification_edits(
    plan: VerificationPlan,
) -> Result[tuple[_Edit, ...], str]:
    reserved = set(plan.reserved_names)
    next_identifier = 1
    edits: list[_Edit] = []
    for obligation in plan.obligations:
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

            assignments.append(
                f"{name}: {emitted.unwrap()} = {obligation.expression_text}"
            )
            expected_types.append(emitted.unwrap())

        if not assignments:
            continue

        text = _render_verification_assignments(assignments, obligation)
        edits.append(
            _Edit(
                start=obligation.insertion_offset,
                end=obligation.insertion_offset,
                text=text,
                authored_span=obligation.expression_span,
                provenance=ReturnCheckProvenance(
                    callable_name=obligation.qualified_name,
                    return_annotation=obligation.return_annotation,
                    controller_parameter=obligation.controller_parameter,
                    narrowed_inputs=obligation.narrowed_inputs,
                    expected_types=tuple(expected_types),
                ),
            )
        )

    return Success(tuple(edits))


def _render_verification_assignments(
    assignments: list[str], obligation: ReturnObligation
) -> str:
    if obligation.inline:
        return "; ".join(assignments) + "; "

    separator = f"\n{obligation.indentation}"
    rendered = separator.join(assignments)
    if obligation.starts_line:
        prefix = "\n" if obligation.leading_newline else ""
        return f"{prefix}{obligation.indentation}{rendered}\n"

    return f"{rendered}{separator}"


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
