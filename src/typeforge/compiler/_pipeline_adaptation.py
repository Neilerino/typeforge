"""Adapt source syntax into lowering IR and expand semantic type relationships."""

from functools import singledispatch
from typing import assert_never

from returns.result import Result, safe

from typeforge.compiler._markers import (
    AllMarker,
    AnyMarker,
    AssignableMarker,
    CaseMarker,
    CollectMarker,
    DefaultMarker,
    DropMarker,
    EachMarker,
    EqualMarker,
    FieldMarker,
    KeyMarker,
    MapFieldsMarker,
    MapMarker,
    MarkerNormalizationError,
    NormalizedMarker,
    NotMarker,
    OptionalFieldMarker,
    ReadonlyFieldMarker,
    ValueMarker,
    normalize_marker,
)
from typeforge.compiler._pipeline_models import (
    AdaptationError,
    SemanticRelationshipAlias,
)
from typeforge.compiler._pipeline_utils import (
    annotation_contains_default_never,
    collect_imports,
    merge_imports,
)
from typeforge.compiler._type_tree import rewrite_type, rewrite_type_children, walk_type
from typeforge.compiler.lowering import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    ClassDeclaration,
    ClassField,
    CollectType,
    Declaration,
    EachType,
    EqualPredicate,
    FieldType,
    FixedTuple,
    FunctionDeclaration,
    HomogeneousTuple,
    ImportFrom,
    LiteralType,
    MapCase,
    MapFieldsType,
    MapType,
    MapValueType,
    ModuleImport,
    NotPredicate,
    Parameter,
    ParameterKind,
    Predicate,
    RuntimeInputType,
    SchemaType,
    StubModule,
    TypeAliasDeclaration,
    TypeApplication,
    TypeExpression,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    is_predicate,
)
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
    RuntimeInputTypeExpression,
    SchemaTypeExpression,
    SourceModule,
    StarredTypeExpression,
    UnionTypeExpression,
)
from typeforge.compiler.model import (
    ClassDeclaration as SourceClass,
)
from typeforge.compiler.model import (
    FunctionDeclaration as SourceFunction,
)
from typeforge.compiler.model import (
    ParameterKind as SourceParameterKind,
)
from typeforge.compiler.model import (
    TypeAliasDeclaration as SourceTypeAlias,
)
from typeforge.compiler.model import (
    TypeExpression as SourceTypeExpression,
)


def substitute_type(
    expression: TypeExpression, variable: str, replacement: TypeExpression
) -> TypeExpression:
    target = TypeVariable(variable)
    return rewrite_type(
        expression,
        lambda current: replacement if current == target else None,
    )


@safe(exceptions=(AdaptationError,))
def adapt_source_module(
    module: SourceModule,
) -> StubModule:
    imports: tuple[ModuleImport, ...] = collect_imports(module.path)
    semantic_aliases = _collect_semantic_relationship_aliases(module.aliases)
    declarations: list[tuple[int, Declaration]] = []
    for alias in module.aliases:
        if len(alias.qualified_name) != 1:
            continue
        parameter_names = tuple(parameter.name for parameter in alias.type_parameters)
        lowered_alias = TypeAliasDeclaration(
            alias.name,
            _adapt_alias_fallback(alias.name, alias.value, parameter_names),
            tuple(parameter.declaration for parameter in alias.type_parameters),
        )
        declarations.append(
            (
                alias.span.start.line,
                TypeAliasDeclaration(
                    lowered_alias.name,
                    expand_map_aliases(lowered_alias.value, semantic_aliases),
                    lowered_alias.type_parameters,
                ),
            )
        )
    for source_class in module.classes:
        declarations.append(
            (
                source_class.span.start.line,
                expand_class_map_aliases(_adapt_class(source_class), semantic_aliases),
            )
        )
    for function in module.functions:
        if len(function.qualified_name) != 1:
            continue
        declarations.append(
            (
                function.span.start.line,
                expand_function_map_aliases(
                    _adapt_function(function), semantic_aliases
                ),
            )
        )
    all_functions = (
        *module.functions,
        *(method for source_class in module.classes for method in source_class.methods),
    )
    if any(
        function.returns is None
        or any(parameter.annotation is None for parameter in function.parameters)
        for function in all_functions
    ):
        imports = merge_imports((*imports, ImportFrom("typing", ("Any",))))
    if any(
        annotation_contains_default_never(function.returns)
        or any(
            annotation_contains_default_never(parameter.annotation)
            for parameter in function.parameters
        )
        for function in module.functions
    ):
        imports = merge_imports((*imports, ImportFrom("typing", ("Never",))))
    ordered = tuple(
        declaration for _, declaration in sorted(declarations, key=lambda item: item[0])
    )
    return StubModule(module.path.stem, ordered, imports)


@safe(exceptions=(AdaptationError,))
def collect_semantic_relationship_aliases(
    aliases: tuple[SourceTypeAlias, ...],
) -> tuple[SemanticRelationshipAlias, ...]:
    return _collect_semantic_relationship_aliases(aliases)


def _collect_semantic_relationship_aliases(
    aliases: tuple[SourceTypeAlias, ...],
) -> tuple[SemanticRelationshipAlias, ...]:
    semantic: list[SemanticRelationshipAlias] = []
    for alias in aliases:
        value = schema_inner_expression(alias.value)
        if not isinstance(value, MarkerTypeExpression):
            continue
        try:
            normalized = normalize_marker(value)
        except MarkerNormalizationError:
            continue
        if not isinstance(normalized, MapMarker):
            continue
        if len(alias.type_parameters) != 1:
            raise AdaptationError(
                alias.name,
                alias.value.source,
                "relationship aliases require exactly one type parameter",
            )
        parameter = alias.type_parameters[0].name
        relationship = _adapt_type_expression(value, alias.name, (parameter,))
        if not isinstance(relationship, MapType):
            raise AssertionError("relationship adaptation produced a plain type")
        semantic.append(SemanticRelationshipAlias(alias.name, parameter, relationship))
    return tuple(semantic)


def schema_inner_expression(expression: SourceTypeExpression) -> SourceTypeExpression:
    if isinstance(expression, SchemaTypeExpression) and len(expression.arguments) == 1:
        return expression.arguments[0]
    return expression


def collect_semantic_map_aliases(
    aliases: tuple[SourceTypeAlias, ...],
) -> Result[tuple[SemanticRelationshipAlias, ...], AdaptationError]:
    return collect_semantic_relationship_aliases(aliases)


def expand_class_map_aliases(
    declaration: ClassDeclaration,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> ClassDeclaration:
    return ClassDeclaration(
        name=declaration.name,
        bases=tuple(expand_map_aliases(base, aliases) for base in declaration.bases),
        fields=tuple(
            ClassField(
                field.name,
                expand_map_aliases(field.annotation, aliases),
                field.default,
            )
            for field in declaration.fields
        ),
        methods=tuple(
            expand_function_map_aliases(method, aliases)
            if isinstance(method, FunctionDeclaration)
            else method
            for method in declaration.methods
        ),
        type_parameters=declaration.type_parameters,
        keywords=declaration.keywords,
        decorators=declaration.decorators,
    )


def expand_function_map_aliases(
    declaration: FunctionDeclaration,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> FunctionDeclaration:
    return FunctionDeclaration(
        name=declaration.name,
        parameters=tuple(
            Parameter(
                parameter.name,
                expand_map_aliases(parameter.annotation, aliases),
                parameter.kind,
                parameter.default,
            )
            for parameter in declaration.parameters
        ),
        return_type=expand_map_aliases(declaration.return_type, aliases),
        type_parameters=declaration.type_parameters,
        is_async=declaration.is_async,
        decorators=declaration.decorators,
    )


def expand_map_aliases(
    expression: TypeExpression,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> TypeExpression:
    match expression:
        case SchemaType(item):
            return resolve_schema_type(expand_map_aliases(item, aliases))
        case TypeApplication(TypeName(name), (argument,)):
            alias = next((item for item in aliases if item.name == name), None)
            if alias is not None:
                return substitute_type(
                    alias.relationship,
                    alias.parameter,
                    expand_map_aliases(argument, aliases),
                )
        case _:
            pass
    return rewrite_type_children(
        expression,
        lambda child: expand_map_aliases(child, aliases),
    )


def resolve_schema_type(expression: TypeExpression) -> TypeExpression:
    match expression:
        case TypeApplication(constructor, arguments):
            return TypeApplication(
                resolve_schema_type(constructor),
                tuple(resolve_schema_type(argument) for argument in arguments),
            )
        case FixedTuple(items):
            return FixedTuple(tuple(resolve_schema_type(item) for item in items))
        case HomogeneousTuple(item):
            return HomogeneousTuple(resolve_schema_type(item))
        case EachType(item):
            return EachType(resolve_schema_type(item))
        case CollectType(item):
            return CollectType(resolve_schema_type(item))
        case UnpackedType(item):
            return UnpackedType(resolve_schema_type(item))
        case UnionExpression(members):
            return union_types_for_schema(
                tuple(resolve_schema_type(member) for member in members)
            )
        case MapType(subject_expression, cases, default):
            subject = resolve_schema_type(subject_expression)
            if isinstance(subject_expression, RuntimeInputType):
                return union_types_for_schema(
                    (
                        *(resolve_schema_type(case.output_type) for case in cases),
                        resolve_schema_type(default),
                    )
                )
            members = (
                subject.members if isinstance(subject, UnionExpression) else (subject,)
            )
            return union_types_for_schema(
                tuple(
                    _resolve_schema_map_member(member, cases, default)
                    for member in members
                )
            )
        case FieldType(name, value, required, readonly):
            return FieldType(
                resolve_schema_type(name),
                resolve_schema_type(value),
                required,
                readonly,
            )
        case MapFieldsType(record, transform):
            return MapFieldsType(
                resolve_schema_type(record),
                resolve_schema_type(transform),
            )
        case SchemaType(item):
            return SchemaType(resolve_schema_type(item))
        case (
            TypeName()
            | TypeVariable()
            | LiteralType()
            | MapValueType()
            | RuntimeInputType()
        ):
            return expression
        case _ as unreachable:
            assert_never(unreachable)


def _resolve_schema_map_member(
    subject: TypeExpression,
    cases: tuple[MapCase, ...],
    default: TypeExpression,
) -> TypeExpression:
    for index, case in enumerate(cases):
        if is_predicate(case.test):
            result = resolve_schema_predicate(case.test)
            if result is True:
                return resolve_schema_type(case.output_type)
            if result is None:
                return union_types_for_schema(
                    (
                        resolve_schema_type(case.output_type),
                        _resolve_schema_map_member(
                            subject, cases[index + 1 :], default
                        ),
                    )
                )
            continue
        matched, capture = _match_schema_pattern(case.test, subject, None)
        if matched:
            return resolve_schema_type(
                _substitute_schema_capture(case.output_type, capture)
            )
    return resolve_schema_type(default)


def _match_schema_pattern(
    pattern: TypeExpression,
    subject: TypeExpression,
    capture: TypeExpression | None,
) -> tuple[bool, TypeExpression | None]:
    if isinstance(pattern, MapValueType):
        if capture is not None and capture != subject:
            return False, capture
        return True, subject
    if isinstance(pattern, TypeApplication) and isinstance(subject, TypeApplication):
        if resolve_schema_type(pattern.constructor) != resolve_schema_type(
            subject.constructor
        ) or len(pattern.arguments) != len(subject.arguments):
            return False, capture
        current = capture
        for nested_pattern, nested_subject in zip(
            pattern.arguments, subject.arguments, strict=True
        ):
            matched, current = _match_schema_pattern(
                nested_pattern, nested_subject, current
            )
            if not matched:
                return False, current
        return True, current
    return resolve_schema_type(pattern) == subject, capture


def _substitute_schema_capture(
    expression: TypeExpression,
    capture: TypeExpression | None,
) -> TypeExpression:
    return rewrite_type(
        expression,
        lambda current: (
            (capture or TypeName("object"))
            if isinstance(current, MapValueType)
            else None
        ),
    )


def resolve_schema_predicate(predicate: Predicate) -> bool | None:
    match predicate:
        case EqualPredicate(left, right):
            if _type_has_variable(left) or _type_has_variable(right):
                return None
            return resolve_schema_type(left) == resolve_schema_type(right)
        case AssignablePredicate(source, target):
            if _type_has_variable(source) or _type_has_variable(target):
                return None
            return _schema_assignable(
                resolve_schema_type(source), resolve_schema_type(target)
            )
        case AllPredicate(predicates):
            values = tuple(resolve_schema_predicate(item) for item in predicates)
            if False in values:
                return False
            return True if all(value is True for value in values) else None
        case AnyPredicate(predicates):
            values = tuple(resolve_schema_predicate(item) for item in predicates)
            if True in values:
                return True
            return False if all(value is False for value in values) else None
        case NotPredicate(item):
            value = resolve_schema_predicate(item)
            return None if value is None else not value
        case _ as unreachable:
            assert_never(unreachable)


def _schema_assignable(source: TypeExpression, target: TypeExpression) -> bool:
    if source == target or target == TypeName("object"):
        return True
    if isinstance(source, UnionExpression):
        return all(_schema_assignable(member, target) for member in source.members)
    if isinstance(target, UnionExpression):
        return any(_schema_assignable(source, member) for member in target.members)
    return False


def _type_has_variable(expression: TypeExpression) -> bool:
    return any(
        isinstance(node, TypeVariable | RuntimeInputType)
        for node in walk_type(expression)
    )


def union_types_for_schema(expressions: tuple[TypeExpression, ...]) -> TypeExpression:
    members: list[TypeExpression] = []
    for expression in expressions:
        candidates = (
            expression.members
            if isinstance(expression, UnionExpression)
            else (expression,)
        )
        for candidate in candidates:
            if candidate != TypeName("Never") and candidate not in members:
                members.append(candidate)
    if not members:
        return TypeName("Never")
    if len(members) == 1:
        return members[0]
    return UnionExpression(tuple(members))


@safe(exceptions=(AdaptationError,))
def adapt_alias(
    alias: SourceTypeAlias,
) -> TypeAliasDeclaration:
    parameter_names = tuple(parameter.name for parameter in alias.type_parameters)
    type_parameters = tuple(
        parameter.declaration for parameter in alias.type_parameters
    )
    return TypeAliasDeclaration(
        alias.name,
        _adapt_alias_fallback(alias.name, alias.value, parameter_names),
        type_parameters,
    )


@safe(exceptions=(AdaptationError,))
def adapt_class(
    source_class: SourceClass,
) -> ClassDeclaration:
    return _adapt_class(source_class)


def _adapt_class(source_class: SourceClass) -> ClassDeclaration:
    parameter_names = tuple(
        parameter.name for parameter in source_class.type_parameters
    )
    bases = _adapt_type_expressions(
        source_class.bases, source_class.name, parameter_names
    )
    fields = tuple(
        ClassField(
            field.name,
            _adapt_type_expression(
                field.annotation, source_class.name, parameter_names
            ),
            "..." if field.has_default else None,
        )
        for field in source_class.fields
    )
    methods = tuple(
        _adapt_function(method, parameter_names) for method in source_class.methods
    )
    return ClassDeclaration(
        name=source_class.name,
        bases=bases,
        fields=fields,
        methods=methods,
        type_parameters=tuple(
            parameter.declaration for parameter in source_class.type_parameters
        ),
        keywords=source_class.keywords,
        decorators=source_class.decorators,
    )


def _adapt_alias_fallback(
    declaration: str,
    expression: SourceTypeExpression,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    if not isinstance(expression, MarkerTypeExpression):
        return _adapt_type_expression(expression, declaration, type_parameters)
    marker = _normalize_marker(declaration, expression)
    match marker:
        case EachMarker(item=item):
            return _adapt_alias_fallback(declaration, item, type_parameters)
        case CollectMarker(item=item):
            return HomogeneousTuple(
                _adapt_alias_fallback(declaration, item, type_parameters)
            )
        case MapMarker() | MapFieldsMarker():
            return TypeName("object")
        case (
            AssignableMarker() | EqualMarker() | AllMarker() | AnyMarker() | NotMarker()
        ):
            return TypeName("bool")
        case (
            CaseMarker(output=value)
            | DefaultMarker(output=value)
            | FieldMarker(value=value)
            | OptionalFieldMarker(value=value)
            | ReadonlyFieldMarker(value=value)
        ):
            return _adapt_alias_fallback(declaration, value, type_parameters)
        case DropMarker():
            return TypeName("Never")
        case KeyMarker():
            return TypeName("str")
        case ValueMarker():
            return TypeName("object")


@safe(exceptions=(AdaptationError,))
def adapt_function(
    function: SourceFunction,
    enclosing_type_parameters: tuple[str, ...] = (),
) -> FunctionDeclaration:
    return _adapt_function(function, enclosing_type_parameters)


def _adapt_function(
    function: SourceFunction,
    enclosing_type_parameters: tuple[str, ...] = (),
) -> FunctionDeclaration:
    parameter_names = tuple(parameter.name for parameter in function.type_parameters)
    visible_type_parameters = (*enclosing_type_parameters, *parameter_names)
    type_parameters = tuple(
        parameter.declaration for parameter in function.type_parameters
    )
    parameters: list[Parameter] = []
    for parameter in function.parameters:
        annotation: TypeExpression = TypeName("Any")
        if parameter.annotation is not None:
            annotation = _adapt_type_expression(
                parameter.annotation,
                function.name,
                visible_type_parameters,
            )
        parameters.append(
            Parameter(
                name=parameter.name,
                annotation=annotation,
                kind=adapt_parameter_kind(parameter.kind),
                default="..." if parameter.has_default else None,
            )
        )
    return_type: TypeExpression = TypeName("Any")
    if function.returns is not None:
        return_type = _adapt_type_expression(
            function.returns,
            function.name,
            visible_type_parameters,
        )
    return FunctionDeclaration(
        name=function.name,
        parameters=tuple(parameters),
        return_type=return_type,
        type_parameters=type_parameters,
        is_async=function.is_async,
        decorators=function.decorators,
    )


@safe(exceptions=(AdaptationError,))
def adapt_type_expression(
    declaration: str,
    expression: SourceTypeExpression,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    return _adapt_type_expression(expression, declaration, type_parameters)


@singledispatch
def _adapt_type_expression(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    raise AdaptationError(
        declaration,
        expression.source,
        f"unsupported type expression {type(expression).__name__}",
    )


@_adapt_type_expression.register
def _(
    expression: SchemaTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    if len(expression.arguments) != 1:
        raise AdaptationError(
            declaration,
            expression.source,
            "Schema requires one type argument",
        )
    return SchemaType(
        _adapt_type_expression(expression.arguments[0], declaration, type_parameters)
    )


@_adapt_type_expression.register
def _(
    expression: RuntimeInputTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    return RuntimeInputType()


@_adapt_type_expression.register
def _(
    expression: NameTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    if expression.source in type_parameters:
        return TypeVariable(expression.source)
    return TypeName(expression.source)


@_adapt_type_expression.register
def _(
    expression: RawTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    return TypeName(expression.source)


@_adapt_type_expression.register
def _(
    expression: UnionTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    return UnionExpression(
        _adapt_type_expressions(expression.members, declaration, type_parameters)
    )


@_adapt_type_expression.register
def _(
    expression: StarredTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    return UnpackedType(
        _adapt_type_expression(expression.item, declaration, type_parameters)
    )


@_adapt_type_expression.register
def _(
    expression: AppliedTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    return TypeApplication(
        _adapt_type_expression(expression.constructor, declaration, type_parameters),
        _adapt_type_expressions(expression.arguments, declaration, type_parameters),
    )


@_adapt_type_expression.register
def _(
    expression: MarkerTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    marker = _normalize_marker(declaration, expression)
    match marker:
        case ValueMarker():
            return MapValueType()
        case MapMarker(subject=subject, entries=entries):
            cases = tuple(
                MapCase(
                    _adapt_map_test(entry.test, declaration, type_parameters),
                    _adapt_type_expression(entry.output, declaration, type_parameters),
                )
                for entry in entries
                if isinstance(entry, CaseMarker)
            )
            default_entry = next(
                (entry for entry in entries if isinstance(entry, DefaultMarker)),
                None,
            )
            default = (
                TypeName("Never")
                if default_entry is None
                else _adapt_type_expression(
                    default_entry.output, declaration, type_parameters
                )
            )
            return MapType(
                _adapt_type_expression(subject, declaration, type_parameters),
                cases,
                default,
            )
        case EachMarker(item=item):
            return EachType(_adapt_type_expression(item, declaration, type_parameters))
        case CollectMarker(item=item):
            return CollectType(
                _adapt_type_expression(item, declaration, type_parameters)
            )
        case _:
            raise AdaptationError(
                declaration,
                expression.source,
                f"unsupported marker {type(marker).__name__.removesuffix('Marker')}",
            )


@safe(exceptions=(AdaptationError,))
def adapt_predicate(
    declaration: str,
    expression: SourceTypeExpression,
    type_parameters: tuple[str, ...],
) -> Predicate:
    return _adapt_predicate(expression, declaration, type_parameters)


def _adapt_map_test(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> TypeExpression | Predicate:
    if isinstance(expression, MarkerTypeExpression):
        marker = _normalize_marker(declaration, expression)
        if isinstance(
            marker,
            EqualMarker | AssignableMarker | AllMarker | AnyMarker | NotMarker,
        ):
            return _adapt_predicate(expression, declaration, type_parameters)
    return _adapt_type_expression(expression, declaration, type_parameters)


def _adapt_predicate(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> Predicate:
    if not isinstance(expression, MarkerTypeExpression):
        raise AdaptationError(
            declaration,
            expression.source,
            "condition must be a Typeforge predicate",
        )
    marker = _normalize_marker(declaration, expression)
    match marker:
        case EqualMarker(left=left, right=right):
            return EqualPredicate(
                _adapt_type_expression(left, declaration, type_parameters),
                _adapt_type_expression(right, declaration, type_parameters),
            )
        case AssignableMarker(left=left, right=right):
            return AssignablePredicate(
                _adapt_type_expression(left, declaration, type_parameters),
                _adapt_type_expression(right, declaration, type_parameters),
            )
        case AllMarker(items=items):
            return AllPredicate(
                tuple(
                    _adapt_predicate(item, declaration, type_parameters)
                    for item in items
                )
            )
        case AnyMarker(items=items):
            return AnyPredicate(
                tuple(
                    _adapt_predicate(item, declaration, type_parameters)
                    for item in items
                )
            )
        case NotMarker(item=item):
            return NotPredicate(_adapt_predicate(item, declaration, type_parameters))
        case _:
            raise AdaptationError(
                declaration,
                expression.source,
                f"{type(marker).__name__.removesuffix('Marker')} is not a predicate",
            )


def _normalize_marker(
    declaration: str,
    expression: MarkerTypeExpression,
) -> NormalizedMarker:
    try:
        return normalize_marker(expression)
    except MarkerNormalizationError as error:
        raise AdaptationError(
            declaration,
            error.source,
            error.message,
        ) from error


def _adapt_type_expressions(
    expressions: tuple[SourceTypeExpression, ...],
    declaration: str,
    type_parameters: tuple[str, ...],
) -> tuple[TypeExpression, ...]:
    return tuple(
        _adapt_type_expression(expression, declaration, type_parameters)
        for expression in expressions
    )


def adapt_parameter_kind(kind: SourceParameterKind) -> ParameterKind:
    return ParameterKind(kind.value)
