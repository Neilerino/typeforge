"""Specialize concrete record applications without rebinding union arguments."""

from dataclasses import dataclass, replace

from typeforge.compiler.adaptation._context import class_type_environment
from typeforge.compiler.adaptation._schema_aliases import expand_schema_aliases
from typeforge.compiler.record_materialization import (
    DerivedRecord,
    RecordMaterialization,
    available_record_name,
    evaluate_record_application,
    is_record_alias,
)
from typeforge.compiler.semantic_adapter import StaticType
from typeforge.compiler.source import (
    AppliedTypeExpression,
    SourceModule,
    SourceSpan,
    annotation_expressions,
    walk_type_expression,
)
from typeforge.compiler.stub_ir import (
    OverloadDeclaration,
    StubModule,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeVariable,
    union_types,
    walk_declaration,
    walk_module,
    walk_type,
)
from typeforge.semantics import RecordShape, RecordUnion


@dataclass(frozen=True, slots=True)
class RecordApplications:
    shapes: tuple[tuple[RecordShape[StaticType], SourceSpan], ...]
    replacements: tuple[tuple[StubTypeExpression, StubTypeExpression], ...]


def materialize_record_applications(
    source: SourceModule, module: StubModule, records: RecordMaterialization
) -> RecordApplications:
    aliases = {alias.name for alias in source.aliases if is_record_alias(alias)}
    origins = _authored_applications(source, module)
    environment = (
        *class_type_environment(source),
        *((shape.name or "", shape) for shape in records.source_shapes),
    )
    known = list(records.derived)
    occupied = {item.name for item in source.identifiers}
    occupied.update(alias.name for alias in source.aliases)
    occupied.update(record.name for record in source.typed_dicts)
    occupied.update(declaration.name for declaration in source.classes)
    occupied.update(function.name for function in source.functions)
    occupied.update(item.shape.name for item in known if item.shape.name is not None)
    replacements: dict[StubTypeExpression, StubTypeExpression] = {}
    shapes: list[tuple[RecordShape[StaticType], SourceSpan]] = []
    for element in walk_module(module):
        match element:
            case TypeApplication(TypeName(alias), (operand,)) if alias in aliases:
                pass
            case _:
                continue

        if element in replacements or any(
            isinstance(item, TypeVariable) for item in walk_type(operand)
        ):
            continue

        origin = origins.get(id(element))
        if origin is None:
            continue

        owner, expression = origin
        declaration = owner or alias
        expanded = expand_schema_aliases(
            expression, source.aliases, declaration=declaration
        ).unwrap()
        result = evaluate_record_application(
            declaration, expression, expanded, environment=environment
        ).unwrap()
        members = result.members if isinstance(result, RecordUnion) else (result,)
        outputs: list[StubTypeExpression] = []
        for member in members:
            existing = _existing_shape(alias, member, known)
            if existing is None:
                name = available_record_name(
                    f"{alias}_{member.name or 'Record'}", occupied
                )
                existing = replace(member, name=name)
                occupied.add(name)
                known.append(
                    DerivedRecord(alias, member.name or "", existing, member.name)
                )
                shapes.append((existing, expression.span))

            outputs.append(TypeName(existing.name or "object"))

        replacements[element] = union_types(tuple(outputs))

    return RecordApplications(tuple(shapes), tuple(replacements.items()))


def _authored_applications(
    source: SourceModule, module: StubModule
) -> dict[int, tuple[str, AppliedTypeExpression]]:
    """Reconcile expression origins with their authored declaration owners."""
    roots = (
        *(alias.value for alias in source.aliases),
        *annotation_expressions(source),
    )
    authored = {
        item.span: item
        for root in roots
        for item in walk_type_expression(root)
        if isinstance(item, AppliedTypeExpression)
    }
    owners = {
        id(element): (
            declaration.fallback.name
            if isinstance(declaration, OverloadDeclaration)
            else declaration.name
        )
        for declaration in module.declarations
        for element in walk_declaration(declaration)
    }
    return {
        id(origin.generated): (
            owners.get(id(origin.generated), ""),
            authored[origin.origin],
        )
        for origin in module.origins
        if origin.origin in authored
    }


def _existing_shape(
    alias: str,
    member: RecordShape[StaticType],
    known: list[DerivedRecord],
) -> RecordShape[StaticType] | None:
    """Reuse an equal output only within the same alias and source alternative."""
    return next(
        (
            item.shape
            for item in known
            if item.alias == alias
            and item.source_name == member.name
            and replace(member, name=item.shape.name) == item.shape
        ),
        None,
    )
