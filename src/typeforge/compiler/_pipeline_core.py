"""Source-to-lowering adaptation and semantic type-expression expansion."""

from functools import singledispatch
from typing import assert_never

from returns.result import Result, safe

from typeforge.compiler._pipeline_models import (
    AdaptationError,
    SemanticRelationshipAlias,
)
from typeforge.compiler._pipeline_utils import (
    annotation_contains_default_never,
    collect_imports,
    merge_imports,
)
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
    IfType,
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
)
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerKind,
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
    if expression == TypeVariable(variable):
        return replacement
    match expression:
        case TypeApplication(constructor, arguments):
            return TypeApplication(
                substitute_type(constructor, variable, replacement),
                tuple(
                    substitute_type(argument, variable, replacement)
                    for argument in arguments
                ),
            )
        case FixedTuple(items):
            return FixedTuple(
                tuple(substitute_type(item, variable, replacement) for item in items)
            )
        case HomogeneousTuple(item):
            return HomogeneousTuple(substitute_type(item, variable, replacement))
        case EachType(item):
            return EachType(substitute_type(item, variable, replacement))
        case CollectType(item):
            return CollectType(substitute_type(item, variable, replacement))
        case UnpackedType(item):
            return UnpackedType(substitute_type(item, variable, replacement))
        case UnionExpression(members):
            return UnionExpression(
                tuple(
                    substitute_type(member, variable, replacement) for member in members
                )
            )
        case IfType(condition, when_true, when_false):
            return IfType(
                substitute_predicate(condition, variable, replacement),
                substitute_type(when_true, variable, replacement),
                substitute_type(when_false, variable, replacement),
            )
        case MapType(subject, cases, default):
            return MapType(
                substitute_type(subject, variable, replacement),
                tuple(
                    MapCase(
                        substitute_type(case.input_type, variable, replacement),
                        substitute_type(case.output_type, variable, replacement),
                    )
                    for case in cases
                ),
                substitute_type(default, variable, replacement),
            )
        case FieldType(name, value, required, readonly):
            return FieldType(
                substitute_type(name, variable, replacement),
                substitute_type(value, variable, replacement),
                required,
                readonly,
            )
        case MapFieldsType(record, transform):
            return MapFieldsType(
                substitute_type(record, variable, replacement),
                substitute_type(transform, variable, replacement),
            )
        case SchemaType(item):
            return SchemaType(substitute_type(item, variable, replacement))
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


def substitute_predicate(
    predicate: Predicate, variable: str, replacement: TypeExpression
) -> Predicate:
    match predicate:
        case EqualPredicate(left, right):
            return EqualPredicate(
                substitute_type(left, variable, replacement),
                substitute_type(right, variable, replacement),
            )
        case AssignablePredicate(source, target):
            return AssignablePredicate(
                substitute_type(source, variable, replacement),
                substitute_type(target, variable, replacement),
            )
        case AllPredicate(predicates):
            return AllPredicate(
                tuple(
                    substitute_predicate(item, variable, replacement)
                    for item in predicates
                )
            )
        case AnyPredicate(predicates):
            return AnyPredicate(
                tuple(
                    substitute_predicate(item, variable, replacement)
                    for item in predicates
                )
            )
        case NotPredicate(item):
            return NotPredicate(substitute_predicate(item, variable, replacement))
        case _ as unreachable:
            assert_never(unreachable)


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
        if not (
            isinstance(value, MarkerTypeExpression)
            and value.marker in {MarkerKind.MAP, MarkerKind.IF}
        ):
            continue
        if len(alias.type_parameters) != 1:
            raise AdaptationError(
                alias.name,
                alias.value.source,
                "relationship aliases require exactly one type parameter",
            )
        parameter = alias.type_parameters[0].name
        relationship = _adapt_type_expression(value, alias.name, (parameter,))
        if not isinstance(relationship, MapType | IfType):
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
    if isinstance(expression, SchemaType):
        return resolve_schema_type(expand_map_aliases(expression.item, aliases))
    if (
        isinstance(expression, TypeApplication)
        and isinstance(expression.constructor, TypeName)
        and len(expression.arguments) == 1
    ):
        alias = next(
            (item for item in aliases if item.name == expression.constructor.name),
            None,
        )
        if alias is not None:
            argument = expand_map_aliases(expression.arguments[0], aliases)
            return substitute_type(alias.relationship, alias.parameter, argument)
    match expression:
        case TypeApplication(constructor, arguments):
            return TypeApplication(
                expand_map_aliases(constructor, aliases),
                tuple(expand_map_aliases(argument, aliases) for argument in arguments),
            )
        case FixedTuple(items):
            return FixedTuple(
                tuple(expand_map_aliases(item, aliases) for item in items)
            )
        case HomogeneousTuple(item):
            return HomogeneousTuple(expand_map_aliases(item, aliases))
        case CollectType(item):
            return CollectType(expand_map_aliases(item, aliases))
        case EachType(item):
            return EachType(expand_map_aliases(item, aliases))
        case UnpackedType(item):
            return UnpackedType(expand_map_aliases(item, aliases))
        case UnionExpression(members):
            return UnionExpression(
                tuple(expand_map_aliases(member, aliases) for member in members)
            )
        case IfType(condition, when_true, when_false):
            return IfType(
                _expand_map_aliases_in_predicate(condition, aliases),
                expand_map_aliases(when_true, aliases),
                expand_map_aliases(when_false, aliases),
            )
        case MapType(subject, cases, default):
            return MapType(
                expand_map_aliases(subject, aliases),
                tuple(
                    MapCase(
                        expand_map_aliases(case.input_type, aliases),
                        expand_map_aliases(case.output_type, aliases),
                    )
                    for case in cases
                ),
                expand_map_aliases(default, aliases),
            )
        case FieldType(name, value, required, readonly):
            return FieldType(
                expand_map_aliases(name, aliases),
                expand_map_aliases(value, aliases),
                required,
                readonly,
            )
        case MapFieldsType(record, transform):
            return MapFieldsType(
                expand_map_aliases(record, aliases),
                expand_map_aliases(transform, aliases),
            )
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


def _expand_map_aliases_in_predicate(
    predicate: Predicate,
    aliases: tuple[SemanticRelationshipAlias, ...],
) -> Predicate:
    match predicate:
        case EqualPredicate(left, right):
            return EqualPredicate(
                expand_map_aliases(left, aliases),
                expand_map_aliases(right, aliases),
            )
        case AssignablePredicate(source, target):
            return AssignablePredicate(
                expand_map_aliases(source, aliases),
                expand_map_aliases(target, aliases),
            )
        case AllPredicate(predicates):
            return AllPredicate(
                tuple(
                    _expand_map_aliases_in_predicate(item, aliases)
                    for item in predicates
                )
            )
        case AnyPredicate(predicates):
            return AnyPredicate(
                tuple(
                    _expand_map_aliases_in_predicate(item, aliases)
                    for item in predicates
                )
            )
        case NotPredicate(item):
            return NotPredicate(_expand_map_aliases_in_predicate(item, aliases))
        case _ as unreachable:
            assert_never(unreachable)


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
        case IfType(condition, when_true, when_false):
            resolved = resolve_schema_predicate(condition)
            if resolved is True:
                return resolve_schema_type(when_true)
            if resolved is False:
                return resolve_schema_type(when_false)
            return union_types_for_schema(
                (
                    resolve_schema_type(when_true),
                    resolve_schema_type(when_false),
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
    for case in cases:
        matched, capture = _match_schema_pattern(case.input_type, subject, None)
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
    match expression:
        case MapValueType():
            return capture or TypeName("object")
        case TypeApplication(constructor, arguments):
            return TypeApplication(
                _substitute_schema_capture(constructor, capture),
                tuple(
                    _substitute_schema_capture(argument, capture)
                    for argument in arguments
                ),
            )
        case FixedTuple(items):
            return FixedTuple(
                tuple(_substitute_schema_capture(item, capture) for item in items)
            )
        case HomogeneousTuple(item):
            return HomogeneousTuple(_substitute_schema_capture(item, capture))
        case EachType(item):
            return EachType(_substitute_schema_capture(item, capture))
        case CollectType(item):
            return CollectType(_substitute_schema_capture(item, capture))
        case UnpackedType(item):
            return UnpackedType(_substitute_schema_capture(item, capture))
        case UnionExpression(members):
            return UnionExpression(
                tuple(_substitute_schema_capture(member, capture) for member in members)
            )
        case IfType(condition, when_true, when_false):
            return IfType(
                _substitute_schema_capture_predicate(condition, capture),
                _substitute_schema_capture(when_true, capture),
                _substitute_schema_capture(when_false, capture),
            )
        case MapType(subject, cases, default):
            return MapType(
                _substitute_schema_capture(subject, capture),
                tuple(
                    MapCase(
                        _substitute_schema_capture(case.input_type, capture),
                        _substitute_schema_capture(case.output_type, capture),
                    )
                    for case in cases
                ),
                _substitute_schema_capture(default, capture),
            )
        case FieldType(name, value, required, readonly):
            return FieldType(
                _substitute_schema_capture(name, capture),
                _substitute_schema_capture(value, capture),
                required,
                readonly,
            )
        case MapFieldsType(record, transform):
            return MapFieldsType(
                _substitute_schema_capture(record, capture),
                _substitute_schema_capture(transform, capture),
            )
        case SchemaType(item):
            return SchemaType(_substitute_schema_capture(item, capture))
        case TypeName() | TypeVariable() | LiteralType() | RuntimeInputType():
            return expression
        case _ as unreachable:
            assert_never(unreachable)


def _substitute_schema_capture_predicate(
    predicate: Predicate,
    capture: TypeExpression | None,
) -> Predicate:
    match predicate:
        case EqualPredicate(left, right):
            return EqualPredicate(
                _substitute_schema_capture(left, capture),
                _substitute_schema_capture(right, capture),
            )
        case AssignablePredicate(source, target):
            return AssignablePredicate(
                _substitute_schema_capture(source, capture),
                _substitute_schema_capture(target, capture),
            )
        case AllPredicate(predicates):
            return AllPredicate(
                tuple(
                    _substitute_schema_capture_predicate(item, capture)
                    for item in predicates
                )
            )
        case AnyPredicate(predicates):
            return AnyPredicate(
                tuple(
                    _substitute_schema_capture_predicate(item, capture)
                    for item in predicates
                )
            )
        case NotPredicate(item):
            return NotPredicate(_substitute_schema_capture_predicate(item, capture))
        case _ as unreachable:
            assert_never(unreachable)


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
    match expression:
        case TypeVariable() | RuntimeInputType():
            return True
        case TypeApplication(constructor, arguments):
            return _type_has_variable(constructor) or any(
                _type_has_variable(argument) for argument in arguments
            )
        case FixedTuple(items):
            return any(_type_has_variable(item) for item in items)
        case (
            HomogeneousTuple(item)
            | EachType(item)
            | CollectType(item)
            | UnpackedType(item)
            | SchemaType(item)
        ):
            return _type_has_variable(item)
        case UnionExpression(members):
            return any(_type_has_variable(member) for member in members)
        case IfType(condition, when_true, when_false):
            return (
                _predicate_has_variable(condition)
                or _type_has_variable(when_true)
                or _type_has_variable(when_false)
            )
        case MapType(subject, cases, default):
            return (
                _type_has_variable(subject)
                or any(
                    _type_has_variable(case.input_type)
                    or _type_has_variable(case.output_type)
                    for case in cases
                )
                or _type_has_variable(default)
            )
        case FieldType(name, value):
            return _type_has_variable(name) or _type_has_variable(value)
        case MapFieldsType(record, transform):
            return _type_has_variable(record) or _type_has_variable(transform)
        case TypeName() | LiteralType() | MapValueType():
            return False
        case _ as unreachable:
            assert_never(unreachable)


def _predicate_has_variable(predicate: Predicate) -> bool:
    match predicate:
        case EqualPredicate(left, right):
            return _type_has_variable(left) or _type_has_variable(right)
        case AssignablePredicate(source, target):
            return _type_has_variable(source) or _type_has_variable(target)
        case AllPredicate(predicates) | AnyPredicate(predicates):
            return any(_predicate_has_variable(item) for item in predicates)
        case NotPredicate(item):
            return _predicate_has_variable(item)
        case _ as unreachable:
            assert_never(unreachable)


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
    arguments = expression.arguments
    marker = expression.marker
    if marker is MarkerKind.EACH:
        return _adapt_single_alias_argument(declaration, expression, type_parameters)
    if marker is MarkerKind.COLLECT:
        return HomogeneousTuple(
            _adapt_single_alias_argument(declaration, expression, type_parameters)
        )
    if marker is MarkerKind.IF:
        _require_marker_arity(declaration, expression, 3, "three")
        return UnionExpression(
            _adapt_type_expressions(arguments[1:], declaration, type_parameters)
        )
    if marker in {MarkerKind.MAP, MarkerKind.MAP_FIELDS}:
        return TypeName("object")
    if marker in {
        MarkerKind.ASSIGNABLE,
        MarkerKind.EQUAL,
        MarkerKind.ALL,
        MarkerKind.ANY,
        MarkerKind.NOT,
    }:
        return TypeName("bool")
    if marker in {
        MarkerKind.CASE,
        MarkerKind.DEFAULT,
        MarkerKind.FIELD,
        MarkerKind.OPTIONAL_FIELD,
        MarkerKind.READONLY_FIELD,
    }:
        if not arguments:
            raise AdaptationError(
                declaration,
                expression.source,
                f"{marker.value} requires a value type",
            )
        return _adapt_alias_fallback(declaration, arguments[-1], type_parameters)
    if marker is MarkerKind.DROP:
        return TypeName("Never")
    if marker is MarkerKind.KEY:
        return TypeName("str")
    return TypeName("object")


def _adapt_single_alias_argument(
    declaration: str,
    expression: MarkerTypeExpression,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    _require_marker_arity(declaration, expression, 1, "one")
    return _adapt_alias_fallback(
        declaration,
        expression.arguments[0],
        type_parameters,
    )


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
    if expression.marker is MarkerKind.VALUE:
        _require_marker_arity(declaration, expression, 0, "no")
        return MapValueType()
    if expression.marker is MarkerKind.IF:
        return _adapt_if_expression(declaration, expression, type_parameters)
    if expression.marker is MarkerKind.MAP:
        return _adapt_map_expression(declaration, expression, type_parameters)
    _require_marker_arity(declaration, expression, 1, "one")
    if expression.marker not in {MarkerKind.EACH, MarkerKind.COLLECT}:
        raise AdaptationError(
            declaration,
            expression.source,
            f"unsupported marker {expression.marker.value}",
        )
    marker_type = EachType if expression.marker is MarkerKind.EACH else CollectType
    return marker_type(
        _adapt_type_expression(expression.arguments[0], declaration, type_parameters)
    )


def _adapt_if_expression(
    declaration: str,
    expression: MarkerTypeExpression,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    _require_marker_arity(declaration, expression, 3, "three")
    condition = _adapt_predicate(expression.arguments[0], declaration, type_parameters)
    branches = _adapt_type_expressions(
        expression.arguments[1:], declaration, type_parameters
    )
    return IfType(condition, branches[0], branches[1])


def _adapt_map_expression(
    declaration: str,
    expression: MarkerTypeExpression,
    type_parameters: tuple[str, ...],
) -> TypeExpression:
    if len(expression.arguments) < 2:
        raise AdaptationError(
            declaration,
            expression.source,
            "Map requires a subject and at least one Case or Default",
        )
    subject = _adapt_type_expression(
        expression.arguments[0], declaration, type_parameters
    )
    cases: list[MapCase] = []
    default: TypeExpression = TypeName("Never")
    for entry in expression.arguments[1:]:
        if not isinstance(entry, MarkerTypeExpression):
            raise _invalid_map_entry(declaration, entry)
        if entry.marker is MarkerKind.CASE and len(entry.arguments) == 2:
            values = _adapt_type_expressions(
                entry.arguments, declaration, type_parameters
            )
            cases.append(MapCase(values[0], values[1]))
        elif entry.marker is MarkerKind.DEFAULT and len(entry.arguments) == 1:
            default = _adapt_type_expression(
                entry.arguments[0], declaration, type_parameters
            )
        else:
            raise _invalid_map_entry(declaration, entry)
    return MapType(subject, tuple(cases), default)


@safe(exceptions=(AdaptationError,))
def adapt_predicate(
    declaration: str,
    expression: SourceTypeExpression,
    type_parameters: tuple[str, ...],
) -> Predicate:
    return _adapt_predicate(expression, declaration, type_parameters)


def _adapt_predicate(
    expression: SourceTypeExpression,
    declaration: str,
    type_parameters: tuple[str, ...],
) -> Predicate:
    if not isinstance(expression, MarkerTypeExpression):
        raise AdaptationError(
            declaration,
            expression.source,
            "If condition must be a Typeforge predicate",
        )
    if expression.marker in {MarkerKind.EQUAL, MarkerKind.ASSIGNABLE}:
        _require_marker_arity(declaration, expression, 2, "two")
        operands = _adapt_type_expressions(
            expression.arguments, declaration, type_parameters
        )
        if expression.marker is MarkerKind.EQUAL:
            return EqualPredicate(operands[0], operands[1])
        return AssignablePredicate(operands[0], operands[1])
    if expression.marker in {MarkerKind.ALL, MarkerKind.ANY}:
        predicates = tuple(
            _adapt_predicate(argument, declaration, type_parameters)
            for argument in expression.arguments
        )
        if expression.marker is MarkerKind.ALL:
            return AllPredicate(predicates)
        return AnyPredicate(predicates)
    if expression.marker is MarkerKind.NOT:
        _require_marker_arity(declaration, expression, 1, "one")
        return NotPredicate(
            _adapt_predicate(expression.arguments[0], declaration, type_parameters)
        )
    raise AdaptationError(
        declaration,
        expression.source,
        f"{expression.marker.value} is not a predicate",
    )


def _require_marker_arity(
    declaration: str,
    expression: MarkerTypeExpression,
    count: int,
    count_name: str,
) -> None:
    if len(expression.arguments) != count:
        raise AdaptationError(
            declaration,
            expression.source,
            f"{expression.marker.value} requires {count_name} type arguments",
        )


def _invalid_map_entry(
    declaration: str, expression: SourceTypeExpression
) -> AdaptationError:
    return AdaptationError(
        declaration,
        expression.source,
        "Map entries must be Case[Input, Output] or Default[Output]",
    )


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
