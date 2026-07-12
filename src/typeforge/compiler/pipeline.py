import ast
from dataclasses import dataclass
from pathlib import Path

from typeforge._result import Err, Ok, Result
from typeforge.compiler import evaluator as record_evaluator
from typeforge.compiler.emitter import emit_stub_module
from typeforge.compiler.frontend import FrontendError, parse_module
from typeforge.compiler.lowering import (
    AllPredicate,
    AnyPredicate,
    ArityFrontier,
    AssignablePredicate,
    ClassDeclaration,
    ClassField,
    CollectType,
    Declaration,
    EachType,
    EqualPredicate,
    FunctionDeclaration,
    HomogeneousTuple,
    IfType,
    ImportFrom,
    LoweringError,
    MapCase,
    MapType,
    MapValueType,
    NotPredicate,
    OverloadDeclaration,
    Parameter,
    ParameterKind,
    Predicate,
    StubModule,
    TypeAliasDeclaration,
    TypeApplication,
    TypeExpression,
    TypeName,
    TypeVariable,
    UnionExpression,
    UnpackedType,
    lower_variadic_module,
)
from typeforge.compiler.model import (
    AppliedTypeExpression,
    MarkerKind,
    MarkerTypeExpression,
    NameTypeExpression,
    RawTypeExpression,
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
    TypedDictDeclaration as SourceTypedDict,
)
from typeforge.compiler.model import (
    TypeExpression as SourceTypeExpression,
)
from typeforge.compiler.records import (
    NamedType,
    NeverType,
    StaticType,
    TypedDictShape,
    UnionType,
)
from typeforge.compiler.records import (
    TypedDictField as StaticTypedDictField,
)


@dataclass(frozen=True, slots=True)
class AdaptationError:
    declaration: str
    expression: str
    message: str


@dataclass(frozen=True, slots=True)
class EmissionError:
    message: str


@dataclass(frozen=True, slots=True)
class UnsupportedPublicDeclaration:
    path: Path
    line: int
    message: str


type GenerationError = (
    FrontendError
    | AdaptationError
    | LoweringError
    | EmissionError
    | UnsupportedPublicDeclaration
)


@dataclass(frozen=True, slots=True)
class GeneratedModule:
    source_path: Path
    content: str


@dataclass(frozen=True, slots=True)
class _DerivedRecord:
    alias: str
    input_name: str
    shape: TypedDictShape


@dataclass(frozen=True, slots=True)
class _RecordMaterialization:
    declarations: tuple[str, ...]
    replacements: tuple[tuple[str, OverloadDeclaration], ...]
    imports: tuple[ImportFrom, ...]


@dataclass(frozen=True, slots=True)
class _ModuleVariables:
    declarations: tuple[str, ...]
    requires_any: bool


@dataclass(frozen=True, slots=True)
class _SemanticMapAlias:
    name: str
    parameter: str
    mapping: MapType


def generate_module(
    path: Path,
    maximum_arity: int,
) -> Result[GeneratedModule, GenerationError]:
    parsed = parse_module(path)
    if isinstance(parsed, Err):
        return Err(parsed.error)
    validated = validate_public_surface(parsed.value)
    if isinstance(validated, Err):
        return Err(validated.error)
    adapted = adapt_source_module(parsed.value)
    if isinstance(adapted, Err):
        return Err(adapted.error)
    records = materialize_record_transforms(parsed.value, adapted.value)
    if isinstance(records, Err):
        return Err(records.error)
    prepared = apply_record_materialization(adapted.value, records.value)
    lowered = lower_variadic_module(prepared, ArityFrontier(0, maximum_arity))
    if isinstance(lowered, Err):
        return Err(lowered.error)
    emitted = emit_stub_module(lowered.value)
    if isinstance(emitted, Err):
        return Err(EmissionError(emitted.error))
    variables = collect_module_variables(parsed.value.path)
    imports = lowered.value.imports
    if variables.requires_any:
        imports = merge_imports((*imports, ImportFrom("typing", ("Any",))))
        emitted = emit_stub_module(
            StubModule(lowered.value.name, lowered.value.declarations, imports)
        )
        if isinstance(emitted, Err):
            return Err(EmissionError(emitted.error))
    content = inject_declarations(
        emitted.value,
        (*records.value.declarations, *variables.declarations),
    )
    return Ok(GeneratedModule(path, content))


def materialize_record_transforms(
    module: SourceModule, stub: StubModule
) -> Result[_RecordMaterialization, AdaptationError]:
    if not module.typed_dicts:
        return Ok(_RecordMaterialization((), (), ()))
    source_shapes = build_record_shapes(module.typed_dicts)
    derived_result = derive_record_shapes(module.aliases, source_shapes)
    if isinstance(derived_result, Err):
        return derived_result
    derived = derived_result.value
    replacements: list[tuple[str, OverloadDeclaration]] = []
    source_functions = {
        function.name: function
        for function in module.functions
        if len(function.qualified_name) == 1
    }
    stub_functions = {
        declaration.name: declaration
        for declaration in stub.declarations
        if isinstance(declaration, FunctionDeclaration)
    }
    for name, source_function in source_functions.items():
        if name not in stub_functions or source_function.returns is None:
            continue
        alias_reference = map_fields_alias_reference(
            source_function.returns, module.aliases
        )
        if alias_reference is None:
            continue
        alias_name, controller = alias_reference
        specialized = tuple(
            specialize_record_function(
                stub_functions[name], controller, item.input_name, item.shape.name
            )
            for item in derived
            if item.alias == alias_name and item.shape.name is not None
        )
        if specialized:
            fallback = FunctionDeclaration(
                name=name,
                parameters=stub_functions[name].parameters,
                return_type=TypeName("object"),
                type_parameters=stub_functions[name].type_parameters,
                is_async=stub_functions[name].is_async,
            )
            replacements.append(
                (name, OverloadDeclaration(signatures=specialized, fallback=fallback))
            )
    declarations = tuple(
        render_typed_dict(shape)
        for shape in (*source_shapes, *(item.shape for item in derived))
    )
    typing_names = {"TypedDict"}
    if replacements:
        typing_names.add("overload")
    if any(
        not field.required for shape in source_shapes for field in shape.fields
    ) or any(not field.required for item in derived for field in item.shape.fields):
        typing_names.add("NotRequired")
    if any(field.readonly for shape in source_shapes for field in shape.fields) or any(
        field.readonly for item in derived for field in item.shape.fields
    ):
        typing_names.add("ReadOnly")
    if any(
        static_type_contains_never(field.value)
        for item in derived
        for field in item.shape.fields
    ):
        typing_names.add("Never")
    return Ok(
        _RecordMaterialization(
            declarations=declarations,
            replacements=tuple(replacements),
            imports=(ImportFrom("typing", tuple(sorted(typing_names))),),
        )
    )


def apply_record_materialization(
    module: StubModule, materialization: _RecordMaterialization
) -> StubModule:
    replacements = dict(materialization.replacements)
    declarations = tuple(
        replacements.get(declaration.name, declaration)
        if isinstance(declaration, FunctionDeclaration)
        else declaration
        for declaration in module.declarations
    )
    imports = merge_imports((*module.imports, *materialization.imports))
    return StubModule(module.name, declarations, imports)


def build_record_shapes(
    declarations: tuple[SourceTypedDict, ...],
) -> tuple[TypedDictShape, ...]:
    shapes: list[TypedDictShape] = []
    by_name: dict[tuple[str, ...], TypedDictShape] = {}
    for declaration in declarations:
        inherited = tuple(
            field
            for base in declaration.bases
            for field in by_name.get(base, TypedDictShape(None, ())).fields
        )
        own_fields = tuple(
            StaticTypedDictField(
                field.name,
                NamedType(field.annotation.source),
                field.required,
                field.readonly,
            )
            for field in declaration.fields
        )
        shape = TypedDictShape(declaration.name, (*inherited, *own_fields))
        shapes.append(shape)
        by_name[declaration.qualified_name] = shape
    return tuple(shapes)


def derive_record_shapes(
    aliases: tuple[SourceTypeAlias, ...], source_shapes: tuple[TypedDictShape, ...]
) -> Result[tuple[_DerivedRecord, ...], AdaptationError]:
    derived: list[_DerivedRecord] = []
    for alias in aliases:
        if not isinstance(alias.value, MarkerTypeExpression):
            continue
        if alias.value.marker is not MarkerKind.MAP_FIELDS:
            continue
        if len(alias.type_parameters) != 1:
            return Err(
                AdaptationError(
                    alias.name,
                    alias.value.source,
                    "MapFields aliases require exactly one type parameter",
                )
            )
        parameter = alias.type_parameters[0].name
        for source_shape in source_shapes:
            output_name = f"{alias.name}_{source_shape.name}"
            expression = adapt_evaluator_expression(
                alias.value, ((parameter, source_shape),), output_name
            )
            if isinstance(expression, Err):
                return Err(
                    AdaptationError(alias.name, alias.value.source, expression.error)
                )
            if not isinstance(expression.value, record_evaluator.MapFields):
                return Err(
                    AdaptationError(
                        alias.name,
                        alias.value.source,
                        "alias must evaluate to MapFields",
                    )
                )
            evaluated = record_evaluator.evaluate_map_fields(expression.value)
            if isinstance(evaluated, Err):
                return Err(
                    AdaptationError(
                        alias.name,
                        alias.value.source,
                        evaluated.error.message,
                    )
                )
            derived.append(
                _DerivedRecord(alias.name, source_shape.name or "", evaluated.value)
            )
    return Ok(tuple(derived))


def adapt_evaluator_expression(
    expression: SourceTypeExpression,
    environment: tuple[tuple[str, StaticType], ...],
    output_name: str | None = None,
) -> Result[record_evaluator.Expression, str]:
    if isinstance(expression, NameTypeExpression):
        bound = dict(environment).get(expression.source)
        return Ok(bound if bound is not None else NamedType(expression.source))
    if isinstance(expression, RawTypeExpression):
        return Ok(NamedType(expression.source))
    if isinstance(expression, AppliedTypeExpression):
        literal = adapt_field_name_literal(expression)
        if literal is not None:
            return Ok(literal)
        return Ok(NamedType(expression.source))
    if isinstance(expression, UnionTypeExpression | StarredTypeExpression):
        return Ok(NamedType(expression.source))
    assert isinstance(expression, MarkerTypeExpression)
    marker = expression.marker
    if marker is MarkerKind.KEY:
        return Ok(record_evaluator.Key())
    if marker is MarkerKind.VALUE:
        return Ok(record_evaluator.Value())
    if marker is MarkerKind.DROP:
        return Ok(record_evaluator.Drop())
    if marker in {
        MarkerKind.FIELD,
        MarkerKind.OPTIONAL_FIELD,
        MarkerKind.READONLY_FIELD,
    }:
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        if isinstance(arguments, Err):
            return arguments
        if len(arguments.value) != 2:
            return Err(f"{marker.value} requires two type arguments")
        if marker is MarkerKind.FIELD:
            return Ok(record_evaluator.Field(*arguments.value))
        if marker is MarkerKind.OPTIONAL_FIELD:
            return Ok(record_evaluator.OptionalField(*arguments.value))
        return Ok(record_evaluator.ReadonlyField(*arguments.value))
    if marker is MarkerKind.MAP_FIELDS:
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        if isinstance(arguments, Err):
            return arguments
        if len(arguments.value) != 2:
            return Err("MapFields requires two type arguments")
        return Ok(
            record_evaluator.MapFields(
                arguments.value[0], arguments.value[1], output_name
            )
        )
    if marker is MarkerKind.MAP:
        return adapt_evaluator_map(expression, environment)
    if marker is MarkerKind.IF:
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        if isinstance(arguments, Err):
            return arguments
        if len(arguments.value) != 3:
            return Err("If requires three type arguments")
        return Ok(record_evaluator.If(*arguments.value))
    if marker in {MarkerKind.EQUAL, MarkerKind.ASSIGNABLE}:
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        if isinstance(arguments, Err):
            return arguments
        if len(arguments.value) != 2:
            return Err(f"{marker.value} requires two type arguments")
        if marker is MarkerKind.EQUAL:
            return Ok(record_evaluator.Equal(*arguments.value))
        return Ok(record_evaluator.Assignable(*arguments.value))
    if marker in {MarkerKind.ALL, MarkerKind.ANY}:
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        if isinstance(arguments, Err):
            return arguments
        if marker is MarkerKind.ALL:
            return Ok(record_evaluator.All(arguments.value))
        return Ok(record_evaluator.Any(arguments.value))
    if marker is MarkerKind.NOT:
        arguments = adapt_evaluator_expressions(expression.arguments, environment)
        if isinstance(arguments, Err):
            return arguments
        if len(arguments.value) != 1:
            return Err("Not requires one type argument")
        return Ok(record_evaluator.Not(arguments.value[0]))
    return Err(f"unsupported record expression {marker.value}")


def adapt_evaluator_expressions(
    expressions: tuple[SourceTypeExpression, ...],
    environment: tuple[tuple[str, StaticType], ...],
) -> Result[tuple[record_evaluator.Expression, ...], str]:
    adapted: list[record_evaluator.Expression] = []
    for expression in expressions:
        result = adapt_evaluator_expression(expression, environment)
        if isinstance(result, Err):
            return result
        adapted.append(result.value)
    return Ok(tuple(adapted))


def adapt_evaluator_map(
    expression: MarkerTypeExpression,
    environment: tuple[tuple[str, StaticType], ...],
) -> Result[record_evaluator.Expression, str]:
    if len(expression.arguments) < 2:
        return Err("Map requires a subject and at least one Case or Default")
    subject = adapt_evaluator_expression(expression.arguments[0], environment)
    if isinstance(subject, Err):
        return subject
    cases: list[record_evaluator.Case] = []
    default: record_evaluator.Expression | None = None
    for entry in expression.arguments[1:]:
        if not isinstance(entry, MarkerTypeExpression):
            return Err("Map entries must be Case or Default")
        arguments = adapt_evaluator_expressions(entry.arguments, environment)
        if isinstance(arguments, Err):
            return arguments
        if entry.marker is MarkerKind.CASE and len(arguments.value) == 2:
            cases.append(record_evaluator.Case(*arguments.value))
        elif entry.marker is MarkerKind.DEFAULT and len(arguments.value) == 1:
            default = arguments.value[0]
        else:
            return Err("Map entries must be Case[Input, Output] or Default[Output]")
    if default is None:
        return Ok(record_evaluator.Map(subject.value, tuple(cases)))
    return Ok(record_evaluator.Map(subject.value, tuple(cases), default))


def adapt_field_name_literal(
    expression: AppliedTypeExpression,
) -> record_evaluator.FieldName | None:
    if not isinstance(expression.constructor, NameTypeExpression):
        return None
    if expression.constructor.source != "Literal" or len(expression.arguments) != 1:
        return None
    argument = expression.arguments[0]
    if not isinstance(argument, RawTypeExpression):
        return None
    try:
        value = ast.literal_eval(argument.source)
    except SyntaxError, ValueError:
        return None
    return record_evaluator.FieldName(value) if isinstance(value, str) else None


def map_fields_alias_reference(
    expression: SourceTypeExpression,
    aliases: tuple[SourceTypeAlias, ...],
) -> tuple[str, str] | None:
    if not isinstance(expression, AppliedTypeExpression):
        return None
    if not isinstance(expression.constructor, NameTypeExpression):
        return None
    if len(expression.arguments) != 1:
        return None
    argument = expression.arguments[0]
    if not isinstance(argument, NameTypeExpression):
        return None
    alias_name = expression.constructor.source
    if any(
        alias.name == alias_name
        and isinstance(alias.value, MarkerTypeExpression)
        and alias.value.marker is MarkerKind.MAP_FIELDS
        for alias in aliases
    ):
        return alias_name, argument.source
    return None


def specialize_record_function(
    function: FunctionDeclaration,
    controller: str,
    input_name: str,
    output_name: str | None,
) -> FunctionDeclaration:
    concrete_input = TypeName(input_name)
    return FunctionDeclaration(
        name=function.name,
        parameters=tuple(
            Parameter(
                parameter.name,
                substitute_type(parameter.annotation, controller, concrete_input),
                parameter.kind,
                parameter.default,
            )
            for parameter in function.parameters
        ),
        return_type=TypeName(output_name or "object"),
        type_parameters=tuple(
            parameter
            for parameter in function.type_parameters
            if parameter != controller
        ),
        is_async=function.is_async,
    )


def substitute_type(
    expression: TypeExpression, variable: str, replacement: TypeExpression
) -> TypeExpression:
    if expression == TypeVariable(variable):
        return replacement
    if isinstance(expression, TypeApplication):
        return TypeApplication(
            substitute_type(expression.constructor, variable, replacement),
            tuple(
                substitute_type(argument, variable, replacement)
                for argument in expression.arguments
            ),
        )
    if isinstance(expression, EachType):
        return EachType(substitute_type(expression.item, variable, replacement))
    if isinstance(expression, CollectType):
        return CollectType(substitute_type(expression.item, variable, replacement))
    if isinstance(expression, UnionExpression):
        return UnionExpression(
            tuple(
                substitute_type(member, variable, replacement)
                for member in expression.members
            )
        )
    if isinstance(expression, MapType):
        return MapType(
            substitute_type(expression.subject, variable, replacement),
            tuple(
                MapCase(
                    substitute_type(case.input_type, variable, replacement),
                    substitute_type(case.output_type, variable, replacement),
                )
                for case in expression.cases
            ),
            substitute_type(expression.default, variable, replacement),
        )
    return expression


def render_typed_dict(shape: TypedDictShape) -> str:
    fields = tuple(render_typed_dict_field(field) for field in shape.fields)
    body = "\n".join(f"    {field}" for field in fields) or "    pass"
    return f"class {shape.name}(TypedDict):\n{body}"


def render_typed_dict_field(field: StaticTypedDictField) -> str:
    value = render_static_type(field.value)
    if field.readonly:
        value = f"ReadOnly[{value}]"
    if not field.required:
        value = f"NotRequired[{value}]"
    return f"{field.name}: {value}"


def render_static_type(value: StaticType) -> str:
    if isinstance(value, NamedType):
        return value.name
    if isinstance(value, NeverType):
        return "Never"
    if isinstance(value, UnionType):
        return " | ".join(render_static_type(member) for member in value.members)
    return value.name or "object"


def static_type_contains_never(value: StaticType) -> bool:
    if isinstance(value, NeverType):
        return True
    if isinstance(value, UnionType):
        return any(static_type_contains_never(member) for member in value.members)
    return False


def merge_imports(imports: tuple[ImportFrom, ...]) -> tuple[ImportFrom, ...]:
    merged: dict[str, set[str]] = {}
    for item in imports:
        merged.setdefault(item.module, set()).update(item.names)
    return tuple(
        ImportFrom(module, tuple(sorted(names))) for module, names in merged.items()
    )


def inject_declarations(content: str, declarations: tuple[str, ...]) -> str:
    if not declarations:
        return content
    if not content.strip():
        return f"{'\n\n'.join(declarations)}\n"
    rendered = "\n\n".join(declarations)
    lines = content.rstrip().splitlines()
    import_count = 0
    for line in lines:
        if not line.startswith("from "):
            break
        import_count += 1
    if import_count == 0:
        return f"{rendered}\n\n{content.lstrip()}"
    imports = "\n".join(lines[:import_count])
    tail = "\n".join(lines[import_count:]).lstrip()
    if not tail:
        return f"{imports}\n\n{rendered}\n"
    return f"{imports}\n\n{rendered}\n\n{tail}\n"


def annotation_contains_default_never(
    expression: SourceTypeExpression | None,
) -> bool:
    if expression is None:
        return False
    if isinstance(expression, AppliedTypeExpression):
        return annotation_contains_default_never(expression.constructor) or any(
            annotation_contains_default_never(argument)
            for argument in expression.arguments
        )
    if not isinstance(expression, MarkerTypeExpression):
        return False
    if expression.marker is MarkerKind.MAP:
        has_default = any(
            isinstance(argument, MarkerTypeExpression)
            and argument.marker is MarkerKind.DEFAULT
            for argument in expression.arguments[1:]
        )
        if not has_default:
            return True
    return any(
        annotation_contains_default_never(argument) for argument in expression.arguments
    )


def adapt_source_module(
    module: SourceModule,
) -> Result[StubModule, AdaptationError]:
    imports = collect_imports(module.path)
    semantic_aliases_result = collect_semantic_map_aliases(module.aliases)
    if isinstance(semantic_aliases_result, Err):
        return semantic_aliases_result
    semantic_aliases = semantic_aliases_result.value
    declarations: list[tuple[int, Declaration]] = []
    for alias in module.aliases:
        if len(alias.qualified_name) != 1:
            continue
        adapted_alias = adapt_alias(alias)
        if isinstance(adapted_alias, Err):
            return adapted_alias
        declarations.append((alias.span.start.line, adapted_alias.value))
    for source_class in module.classes:
        adapted_class = adapt_class(source_class)
        if isinstance(adapted_class, Err):
            return adapted_class
        declarations.append(
            (
                source_class.span.start.line,
                expand_class_map_aliases(adapted_class.value, semantic_aliases),
            )
        )
    for function in module.functions:
        if len(function.qualified_name) != 1:
            continue
        adapted = adapt_function(function)
        if isinstance(adapted, Err):
            return adapted
        declarations.append(
            (
                function.span.start.line,
                expand_function_map_aliases(adapted.value, semantic_aliases),
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
    return Ok(StubModule(module.path.stem, ordered, imports))


def collect_semantic_map_aliases(
    aliases: tuple[SourceTypeAlias, ...],
) -> Result[tuple[_SemanticMapAlias, ...], AdaptationError]:
    semantic: list[_SemanticMapAlias] = []
    for alias in aliases:
        if not (
            isinstance(alias.value, MarkerTypeExpression)
            and alias.value.marker is MarkerKind.MAP
        ):
            continue
        if len(alias.type_parameters) != 1:
            return Err(
                AdaptationError(
                    alias.name,
                    alias.value.source,
                    "Map aliases require exactly one type parameter",
                )
            )
        parameter = alias.type_parameters[0].name
        adapted = adapt_map_expression(alias.name, alias.value, (parameter,))
        if isinstance(adapted, Err):
            return adapted
        if not isinstance(adapted.value, MapType):
            raise AssertionError("Map adaptation produced a non-Map expression")
        semantic.append(_SemanticMapAlias(alias.name, parameter, adapted.value))
    return Ok(tuple(semantic))


def expand_class_map_aliases(
    declaration: ClassDeclaration,
    aliases: tuple[_SemanticMapAlias, ...],
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
    aliases: tuple[_SemanticMapAlias, ...],
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
    aliases: tuple[_SemanticMapAlias, ...],
) -> TypeExpression:
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
            return substitute_type(alias.mapping, alias.parameter, argument)
    if isinstance(expression, TypeApplication):
        return TypeApplication(
            expand_map_aliases(expression.constructor, aliases),
            tuple(
                expand_map_aliases(argument, aliases)
                for argument in expression.arguments
            ),
        )
    if isinstance(expression, CollectType):
        return CollectType(expand_map_aliases(expression.item, aliases))
    if isinstance(expression, EachType):
        return EachType(expand_map_aliases(expression.item, aliases))
    if isinstance(expression, UnpackedType):
        return UnpackedType(expand_map_aliases(expression.item, aliases))
    if isinstance(expression, UnionExpression):
        return UnionExpression(
            tuple(expand_map_aliases(member, aliases) for member in expression.members)
        )
    return expression


def adapt_alias(
    alias: SourceTypeAlias,
) -> Result[TypeAliasDeclaration, AdaptationError]:
    parameter_names = tuple(parameter.name for parameter in alias.type_parameters)
    type_parameters = tuple(
        parameter.declaration for parameter in alias.type_parameters
    )
    value = adapt_alias_fallback(alias.name, alias.value, parameter_names)
    if isinstance(value, Err):
        return value
    return Ok(TypeAliasDeclaration(alias.name, value.value, type_parameters))


def adapt_class(
    source_class: SourceClass,
) -> Result[ClassDeclaration, AdaptationError]:
    parameter_names = tuple(
        parameter.name for parameter in source_class.type_parameters
    )
    bases = adapt_type_expressions(
        source_class.name, source_class.bases, parameter_names
    )
    if isinstance(bases, Err):
        return bases
    fields: list[ClassField] = []
    for field in source_class.fields:
        annotation = adapt_type_expression(
            source_class.name, field.annotation, parameter_names
        )
        if isinstance(annotation, Err):
            return annotation
        fields.append(
            ClassField(
                field.name,
                annotation.value,
                "..." if field.has_default else None,
            )
        )
    methods: list[FunctionDeclaration] = []
    for method in source_class.methods:
        adapted_method = adapt_function(method, parameter_names)
        if isinstance(adapted_method, Err):
            return adapted_method
        methods.append(adapted_method.value)
    return Ok(
        ClassDeclaration(
            name=source_class.name,
            bases=bases.value,
            fields=tuple(fields),
            methods=tuple(methods),
            type_parameters=tuple(
                parameter.declaration for parameter in source_class.type_parameters
            ),
            keywords=source_class.keywords,
            decorators=source_class.decorators,
        )
    )


def adapt_alias_fallback(
    declaration: str,
    expression: SourceTypeExpression,
    type_parameters: tuple[str, ...],
) -> Result[TypeExpression, AdaptationError]:
    if not isinstance(expression, MarkerTypeExpression):
        return adapt_type_expression(declaration, expression, type_parameters)
    arguments = expression.arguments
    marker = expression.marker
    if marker is MarkerKind.EACH:
        return adapt_single_alias_argument(declaration, expression, type_parameters)
    if marker is MarkerKind.COLLECT:
        item = adapt_single_alias_argument(declaration, expression, type_parameters)
        if isinstance(item, Err):
            return item
        return Ok(HomogeneousTuple(item.value))
    if marker is MarkerKind.IF:
        if len(arguments) != 3:
            return Err(_marker_arity_error(declaration, expression, "three"))
        branches = adapt_type_expressions(declaration, arguments[1:], type_parameters)
        if isinstance(branches, Err):
            return branches
        return Ok(UnionExpression(branches.value))
    if marker in {MarkerKind.MAP, MarkerKind.MAP_FIELDS}:
        return Ok(TypeName("object"))
    if marker in {
        MarkerKind.ASSIGNABLE,
        MarkerKind.EQUAL,
        MarkerKind.ALL,
        MarkerKind.ANY,
        MarkerKind.NOT,
    }:
        return Ok(TypeName("bool"))
    if marker in {
        MarkerKind.CASE,
        MarkerKind.DEFAULT,
        MarkerKind.FIELD,
        MarkerKind.OPTIONAL_FIELD,
        MarkerKind.READONLY_FIELD,
    }:
        if not arguments:
            return Err(
                AdaptationError(
                    declaration,
                    expression.source,
                    f"{marker.value} requires a value type",
                )
            )
        return adapt_alias_fallback(declaration, arguments[-1], type_parameters)
    if marker is MarkerKind.DROP:
        return Ok(TypeName("Never"))
    if marker is MarkerKind.KEY:
        return Ok(TypeName("str"))
    if marker is MarkerKind.VALUE:
        return Ok(TypeName("object"))
    return Ok(TypeName("object"))


def adapt_single_alias_argument(
    declaration: str,
    expression: MarkerTypeExpression,
    type_parameters: tuple[str, ...],
) -> Result[TypeExpression, AdaptationError]:
    if len(expression.arguments) != 1:
        return Err(_marker_arity_error(declaration, expression, "one"))
    return adapt_alias_fallback(
        declaration,
        expression.arguments[0],
        type_parameters,
    )


def validate_public_surface(
    module: SourceModule,
) -> Result[None, UnsupportedPublicDeclaration]:
    source = module.path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module.path), type_comments=True)
    typed_dict_names = {declaration.name for declaration in module.typed_dicts}
    for statement in tree.body:
        unsupported = unsupported_public_statement(statement, typed_dict_names)
        if unsupported is not None:
            return Err(
                UnsupportedPublicDeclaration(
                    module.path,
                    statement.lineno,
                    unsupported,
                )
            )
    return Ok(None)


def unsupported_public_statement(
    statement: ast.stmt,
    typed_dict_names: set[str],
) -> str | None:
    if isinstance(
        statement,
        ast.FunctionDef | ast.AsyncFunctionDef | ast.ImportFrom | ast.Pass,
    ):
        return None
    if isinstance(statement, ast.Import):
        if all(alias.name == "typeforge" for alias in statement.names):
            return None
        return "plain imports are not yet supported; use a from import"
    if isinstance(statement, ast.Expr):
        public_bindings = tuple(
            node.target.id
            for node in ast.walk(statement.value)
            if isinstance(node, ast.NamedExpr) and not node.target.id.startswith("_")
        )
        if public_bindings:
            return "assignment expressions that create public names are not supported"
        return None
    if isinstance(statement, ast.ClassDef):
        if statement.name in typed_dict_names or statement.name.startswith("_"):
            return None
        return unsupported_class_body(statement)
    if isinstance(statement, ast.TypeAlias):
        return None
    if isinstance(statement, ast.Assign):
        names = tuple(
            target.id for target in statement.targets if isinstance(target, ast.Name)
        )
        if names == ("__all__",):
            if static_export_names(statement.value) is not None:
                return None
            return "__all__ must be a literal list or tuple of names"
        return None
    if isinstance(statement, ast.AnnAssign):
        return None
    if isinstance(statement, ast.If) and is_runtime_main_guard(statement):
        if statement.orelse:
            return "runtime main guards with an else branch are not supported"
        return None
    return f"public {type(statement).__name__} declarations are not yet supported"


def unsupported_class_body(declaration: ast.ClassDef) -> str | None:
    for statement in declaration.body:
        if isinstance(
            statement,
            ast.FunctionDef | ast.AsyncFunctionDef | ast.AnnAssign | ast.Pass,
        ):
            continue
        if isinstance(statement, ast.Expr) and isinstance(
            statement.value, ast.Constant
        ):
            continue
        if isinstance(statement, ast.Assign):
            names = tuple(
                target.id
                for target in statement.targets
                if isinstance(target, ast.Name)
            )
            if names and all(name.startswith("_") for name in names):
                continue
        return (
            f"class {declaration.name} contains unsupported "
            f"{type(statement).__name__} declarations"
        )
    return None


def is_runtime_main_guard(statement: ast.If) -> bool:
    test = statement.test
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False
    left = test.left
    right = test.comparators[0]
    return (_is_dunder_name(left) and _is_main_literal(right)) or (
        _is_main_literal(left) and _is_dunder_name(right)
    )


def _is_dunder_name(expression: ast.expr) -> bool:
    return isinstance(expression, ast.Name) and expression.id == "__name__"


def _is_main_literal(expression: ast.expr) -> bool:
    return isinstance(expression, ast.Constant) and expression.value == "__main__"


def adapt_function(
    function: SourceFunction,
    enclosing_type_parameters: tuple[str, ...] = (),
) -> Result[FunctionDeclaration, AdaptationError]:
    parameter_names = tuple(parameter.name for parameter in function.type_parameters)
    visible_type_parameters = (*enclosing_type_parameters, *parameter_names)
    type_parameters = tuple(
        parameter.declaration for parameter in function.type_parameters
    )
    parameters: list[Parameter] = []
    for parameter in function.parameters:
        annotation: TypeExpression = TypeName("Any")
        if parameter.annotation is not None:
            adapted = adapt_type_expression(
                function.name,
                parameter.annotation,
                visible_type_parameters,
            )
            if isinstance(adapted, Err):
                return adapted
            annotation = adapted.value
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
        adapted_return = adapt_type_expression(
            function.name,
            function.returns,
            visible_type_parameters,
        )
        if isinstance(adapted_return, Err):
            return adapted_return
        return_type = adapted_return.value
    return Ok(
        FunctionDeclaration(
            name=function.name,
            parameters=tuple(parameters),
            return_type=return_type,
            type_parameters=type_parameters,
            is_async=function.is_async,
            decorators=function.decorators,
        )
    )


def adapt_type_expression(
    declaration: str,
    expression: SourceTypeExpression,
    type_parameters: tuple[str, ...],
) -> Result[TypeExpression, AdaptationError]:
    if isinstance(expression, NameTypeExpression):
        if expression.source in type_parameters:
            return Ok(TypeVariable(expression.source))
        return Ok(TypeName(expression.source))
    if isinstance(expression, RawTypeExpression):
        return Ok(TypeName(expression.source))
    if isinstance(expression, UnionTypeExpression):
        members = adapt_type_expressions(
            declaration, expression.members, type_parameters
        )
        if isinstance(members, Err):
            return members
        return Ok(UnionExpression(members.value))
    if isinstance(expression, StarredTypeExpression):
        starred_result = adapt_type_expression(
            declaration, expression.item, type_parameters
        )
        return (
            starred_result
            if isinstance(starred_result, Err)
            else Ok(UnpackedType(starred_result.value))
        )
    if isinstance(expression, AppliedTypeExpression):
        constructor = adapt_type_expression(
            declaration,
            expression.constructor,
            type_parameters,
        )
        if isinstance(constructor, Err):
            return constructor
        arguments_result = adapt_type_expressions(
            declaration,
            expression.arguments,
            type_parameters,
        )
        if isinstance(arguments_result, Err):
            return arguments_result
        return Ok(TypeApplication(constructor.value, arguments_result.value))
    assert isinstance(expression, MarkerTypeExpression)
    if expression.marker is MarkerKind.VALUE:
        if expression.arguments:
            return Err(_marker_arity_error(declaration, expression, "no"))
        return Ok(MapValueType())
    if expression.marker is MarkerKind.IF:
        return adapt_if_expression(declaration, expression, type_parameters)
    if expression.marker is MarkerKind.MAP:
        return adapt_map_expression(declaration, expression, type_parameters)
    arguments_result = adapt_type_expressions(
        declaration,
        expression.arguments,
        type_parameters,
    )
    if isinstance(arguments_result, Err):
        return arguments_result
    if len(arguments_result.value) != 1:
        return Err(
            AdaptationError(
                declaration,
                expression.source,
                f"{expression.marker.value} requires one type argument",
            )
        )
    marker_item = arguments_result.value[0]
    if expression.marker is MarkerKind.EACH:
        return Ok(EachType(marker_item))
    if expression.marker is MarkerKind.COLLECT:
        return Ok(CollectType(marker_item))
    return Err(
        AdaptationError(
            declaration,
            expression.source,
            f"unsupported marker {expression.marker.value}",
        )
    )


def adapt_if_expression(
    declaration: str,
    expression: MarkerTypeExpression,
    type_parameters: tuple[str, ...],
) -> Result[TypeExpression, AdaptationError]:
    if len(expression.arguments) != 3:
        return Err(_marker_arity_error(declaration, expression, "three"))
    condition = adapt_predicate(declaration, expression.arguments[0], type_parameters)
    if isinstance(condition, Err):
        return condition
    branches = adapt_type_expressions(
        declaration, expression.arguments[1:], type_parameters
    )
    if isinstance(branches, Err):
        return branches
    return Ok(IfType(condition.value, branches.value[0], branches.value[1]))


def adapt_map_expression(
    declaration: str,
    expression: MarkerTypeExpression,
    type_parameters: tuple[str, ...],
) -> Result[TypeExpression, AdaptationError]:
    if len(expression.arguments) < 2:
        return Err(
            AdaptationError(
                declaration,
                expression.source,
                "Map requires a subject and at least one Case or Default",
            )
        )
    subject = adapt_type_expression(
        declaration, expression.arguments[0], type_parameters
    )
    if isinstance(subject, Err):
        return subject
    cases: list[MapCase] = []
    default: TypeExpression = TypeName("Never")
    for entry in expression.arguments[1:]:
        if not isinstance(entry, MarkerTypeExpression):
            return Err(_invalid_map_entry(declaration, entry))
        if entry.marker is MarkerKind.CASE and len(entry.arguments) == 2:
            values = adapt_type_expressions(
                declaration, entry.arguments, type_parameters
            )
            if isinstance(values, Err):
                return values
            cases.append(MapCase(values.value[0], values.value[1]))
        elif entry.marker is MarkerKind.DEFAULT and len(entry.arguments) == 1:
            adapted_default = adapt_type_expression(
                declaration, entry.arguments[0], type_parameters
            )
            if isinstance(adapted_default, Err):
                return adapted_default
            default = adapted_default.value
        else:
            return Err(_invalid_map_entry(declaration, entry))
    return Ok(MapType(subject.value, tuple(cases), default))


def adapt_predicate(
    declaration: str,
    expression: SourceTypeExpression,
    type_parameters: tuple[str, ...],
) -> Result[Predicate, AdaptationError]:
    if not isinstance(expression, MarkerTypeExpression):
        return Err(
            AdaptationError(
                declaration,
                expression.source,
                "If condition must be a Typeforge predicate",
            )
        )
    if expression.marker in {MarkerKind.EQUAL, MarkerKind.ASSIGNABLE}:
        if len(expression.arguments) != 2:
            return Err(_marker_arity_error(declaration, expression, "two"))
        operands = adapt_type_expressions(
            declaration, expression.arguments, type_parameters
        )
        if isinstance(operands, Err):
            return operands
        if expression.marker is MarkerKind.EQUAL:
            return Ok(EqualPredicate(operands.value[0], operands.value[1]))
        return Ok(AssignablePredicate(operands.value[0], operands.value[1]))
    if expression.marker in {MarkerKind.ALL, MarkerKind.ANY}:
        predicates: list[Predicate] = []
        for argument in expression.arguments:
            adapted = adapt_predicate(declaration, argument, type_parameters)
            if isinstance(adapted, Err):
                return adapted
            predicates.append(adapted.value)
        if expression.marker is MarkerKind.ALL:
            return Ok(AllPredicate(tuple(predicates)))
        return Ok(AnyPredicate(tuple(predicates)))
    if expression.marker is MarkerKind.NOT:
        if len(expression.arguments) != 1:
            return Err(_marker_arity_error(declaration, expression, "one"))
        adapted = adapt_predicate(declaration, expression.arguments[0], type_parameters)
        if isinstance(adapted, Err):
            return adapted
        return Ok(NotPredicate(adapted.value))
    return Err(
        AdaptationError(
            declaration,
            expression.source,
            f"{expression.marker.value} is not a predicate",
        )
    )


def _marker_arity_error(
    declaration: str, expression: MarkerTypeExpression, count: str
) -> AdaptationError:
    return AdaptationError(
        declaration,
        expression.source,
        f"{expression.marker.value} requires {count} type arguments",
    )


def _invalid_map_entry(
    declaration: str, expression: SourceTypeExpression
) -> AdaptationError:
    return AdaptationError(
        declaration,
        expression.source,
        "Map entries must be Case[Input, Output] or Default[Output]",
    )


def adapt_type_expressions(
    declaration: str,
    expressions: tuple[SourceTypeExpression, ...],
    type_parameters: tuple[str, ...],
) -> Result[tuple[TypeExpression, ...], AdaptationError]:
    adapted: list[TypeExpression] = []
    for expression in expressions:
        result = adapt_type_expression(declaration, expression, type_parameters)
        if isinstance(result, Err):
            return result
        adapted.append(result.value)
    return Ok(tuple(adapted))


def adapt_parameter_kind(kind: SourceParameterKind) -> ParameterKind:
    return ParameterKind(kind.value)


def collect_module_variables(path: Path) -> _ModuleVariables:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(path), type_comments=True)
    declarations: list[str] = []
    requires_any = False
    for statement in module.body:
        if isinstance(statement, ast.AnnAssign):
            if not isinstance(statement.target, ast.Name):
                continue
            name = statement.target.id
            if name.startswith("_"):
                continue
            annotation = ast.unparse(statement.annotation)
            declarations.append(f"{name}: {annotation}")
            continue
        if not isinstance(statement, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        ):
            continue
        if (
            statement.type_comment is not None
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            name = statement.targets[0].id
            if not name.startswith("_"):
                declarations.append(f"{name}: {statement.type_comment}")
                requires_any = requires_any or annotation_contains_any(
                    statement.type_comment
                )
            continue
        for target in statement.targets:
            bindings = infer_assignment_bindings(target, statement.value)
            for name, annotation in bindings:
                if name.startswith("_"):
                    continue
                declarations.append(f"{name}: {annotation}")
                requires_any = requires_any or annotation_contains_any(annotation)
    return _ModuleVariables(tuple(declarations), requires_any)


def infer_assignment_bindings(
    target: ast.expr, value: ast.expr
) -> tuple[tuple[str, str], ...]:
    if isinstance(target, ast.Name):
        return ((target.id, infer_value_type(value)),)
    if isinstance(target, ast.Starred):
        return tuple(
            (name, "Any") for name in collect_assignment_target_names(target.value)
        )
    if isinstance(target, ast.Tuple | ast.List):
        values = value.elts if isinstance(value, ast.Tuple | ast.List) else ()
        if len(values) != len(target.elts):
            return tuple(
                (name, "Any") for name in collect_assignment_target_names(target)
            )
        return tuple(
            binding
            for item, item_value in zip(target.elts, values, strict=True)
            for binding in infer_assignment_bindings(item, item_value)
        )
    return ()


def collect_assignment_target_names(target: ast.expr) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, ast.Starred):
        return collect_assignment_target_names(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        return tuple(
            name
            for item in target.elts
            for name in collect_assignment_target_names(item)
        )
    return ()


def infer_value_type(value: ast.expr) -> str:
    if isinstance(value, ast.Constant):
        return infer_constant_type(value.value)
    if isinstance(value, ast.Tuple):
        if not value.elts:
            return "tuple[()]"
        return f"tuple[{', '.join(infer_value_type(item) for item in value.elts)}]"
    if isinstance(value, ast.List):
        return f"list[{infer_collection_item_type(value.elts)}]"
    if isinstance(value, ast.Set):
        return f"set[{infer_collection_item_type(value.elts)}]"
    if isinstance(value, ast.Dict):
        keys = tuple(key for key in value.keys if key is not None)
        if len(keys) != len(value.keys):
            return "dict[Any, Any]"
        key_type = infer_collection_item_type(keys)
        value_type = infer_collection_item_type(value.values)
        return f"dict[{key_type}, {value_type}]"
    if isinstance(value, ast.IfExp):
        return union_annotations(
            (infer_value_type(value.body), infer_value_type(value.orelse))
        )
    if isinstance(value, ast.UnaryOp):
        operand_type = infer_value_type(value.operand)
        if operand_type in {"int", "float", "complex"}:
            return operand_type
        return "Any"
    if isinstance(value, ast.BinOp):
        left = infer_value_type(value.left)
        right = infer_value_type(value.right)
        if left == right and left in {"int", "float", "complex", "str", "bytes"}:
            return left
        return "Any"
    if isinstance(value, ast.Call):
        constructor = infer_constructor_type(value.func)
        return constructor or "Any"
    if isinstance(value, ast.Name) and value.id[:1].isupper():
        return f"type[{value.id}]"
    return "Any"


def infer_constant_type(value: object) -> str:
    if value is None:
        return "None"
    if value is Ellipsis:
        return "Any"
    return type(value).__name__


def infer_collection_item_type(values: tuple[ast.expr, ...] | list[ast.expr]) -> str:
    if not values:
        return "Any"
    return union_annotations(tuple(infer_value_type(value) for value in values))


def union_annotations(annotations: tuple[str, ...]) -> str:
    unique = tuple(dict.fromkeys(annotations))
    return " | ".join(unique)


def infer_constructor_type(function: ast.expr) -> str | None:
    name = constructor_name(function)
    if name is None:
        return None
    terminal = name.rsplit(".", 1)[-1].split("[", 1)[0]
    if terminal[:1].isupper() or terminal in {
        "bytes",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "set",
        "str",
        "tuple",
    }:
        return name
    return None


def constructor_name(function: ast.expr) -> str | None:
    if isinstance(function, ast.Name | ast.Attribute | ast.Subscript):
        return ast.unparse(function)
    return None


def annotation_contains_any(annotation: str) -> bool:
    try:
        parsed = ast.parse(annotation, mode="eval")
    except SyntaxError:
        return annotation == "Any"
    return any(
        isinstance(node, ast.Name) and node.id == "Any" for node in ast.walk(parsed)
    )


def collect_imports(path: Path) -> tuple[ImportFrom, ...]:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(path), type_comments=True)
    exported_names = collect_export_names(module)
    imports: list[ImportFrom] = []
    for statement in module.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        if (
            statement.level == 0
            and statement.module is not None
            and (
                statement.module == "typeforge"
                or statement.module.startswith("typeforge.")
            )
        ):
            continue
        names = tuple(
            render_import_name(alias, exported_names) for alias in statement.names
        )
        module_name = f"{'.' * statement.level}{statement.module or ''}"
        imports.append(ImportFrom(module_name, names))
    return tuple(imports)


def collect_export_names(module: ast.Module) -> frozenset[str]:
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        ):
            continue
        names = static_export_names(statement.value)
        return frozenset(names or ())
    return frozenset()


def static_export_names(expression: ast.expr) -> tuple[str, ...] | None:
    if not isinstance(expression, ast.List | ast.Tuple):
        return None
    names = tuple(
        item.value
        for item in expression.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    )
    if len(names) != len(expression.elts):
        return None
    return names


def render_import_name(alias: ast.alias, exported_names: frozenset[str]) -> str:
    local_name = alias.asname or alias.name
    if alias.asname is not None or local_name in exported_names:
        return f"{alias.name} as {local_name}"
    return alias.name
