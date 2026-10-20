"""Module-level specialization and authored-origin reconciliation."""

from dataclasses import replace

from returns.result import Failure, Result, Success

from typeforge.compiler.semantic_adapter import (
    SemanticEnvironment,
    named_type_environment,
)
from typeforge.compiler.specialization._each_lowering import lower_each_function
from typeforge.compiler.specialization._expressions import type_parameter_name
from typeforge.compiler.specialization._map_lowering import lower_map_function
from typeforge.compiler.specialization._models import (
    ArityFrontier,
    LoweringError,
    LoweringErrorCode,
)
from typeforge.compiler.stub_ir import (
    ClassDeclaration,
    Declaration,
    FunctionDeclaration,
    GeneratedElementOrigin,
    Import,
    ImportFrom,
    LiteralType,
    MapType,
    ModuleImport,
    OverloadDeclaration,
    StubModule,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeRewriteObserver,
    merge_imports,
    walk_declaration,
    walk_module,
)


def lower_variadic_module(
    module: StubModule, frontier: ArityFrontier
) -> Result[StubModule, LoweringError]:
    if frontier.minimum < 0 or frontier.maximum < frontier.minimum:
        return Failure(
            LoweringError(
                LoweringErrorCode.INVALID_FRONTIER,
                module.name,
                "arity frontier must satisfy 0 <= minimum <= maximum",
            )
        )

    lowered: list[Declaration] = []
    origins = module.origins
    expression_origins = list(module.origins)

    def record_rewrite(
        original: StubTypeExpression, replacement: StubTypeExpression
    ) -> None:
        if original is not replacement:
            expression_origins.extend(
                replace(item, generated=replacement)
                for item in tuple(expression_origins)
                if item.generated is original
            )

    has_overloads = False
    environment = named_type_environment(
        tuple(
            (
                item.name,
                (
                    *(
                        name
                        for base in item.bases
                        if (name := _base_name(base)) is not None
                    ),
                    *(("typing.Protocol",) if item.is_protocol else ()),
                ),
            )
            for item in module.declarations
            if isinstance(item, ClassDeclaration)
        )
    )
    for declaration in module.declarations:
        if isinstance(declaration, ClassDeclaration):
            class_result = _lower_class(
                declaration,
                frontier,
                on_rewrite=record_rewrite,
                environment=environment,
            )
            if isinstance(class_result, Failure):
                return class_result

            lowered_class, class_has_overloads = class_result.unwrap()
            has_overloads = has_overloads or class_has_overloads
            lowered.append(lowered_class)
            origins = _replace_declaration_origins(
                origins=origins,
                original=declaration,
                replacement=lowered_class,
            )
            continue

        if not isinstance(declaration, FunctionDeclaration):
            lowered.append(declaration)
            continue

        result = _lower_function(
            declaration, frontier, on_rewrite=record_rewrite, environment=environment
        )
        if isinstance(result, Failure):
            return result

        lowered_declaration = result.unwrap()
        has_overloads = has_overloads or isinstance(
            lowered_declaration, OverloadDeclaration
        )
        lowered.append(lowered_declaration)
        origins = _replace_declaration_origins(
            origins,
            declaration,
            lowered_declaration,
        )

    imports = module.imports
    if has_overloads:
        imports = _add_import(imports, ImportFrom("typing", ("overload",)))

    lowered_module = replace(module, declarations=tuple(lowered), imports=imports)
    order: dict[int, int] = {}
    for element in walk_module(lowered_module):
        order.setdefault(id(element), len(order))

    current_origins = {
        (item.origin, id(item.generated)): item
        for item in (*origins, *expression_origins)
        if id(item.generated) in order
    }
    origins = tuple(
        sorted(
            current_origins.values(),
            key=lambda item: (item.origin.start, order[id(item.generated)]),
        )
    )
    lowered_module = replace(lowered_module, origins=origins)
    if any(
        isinstance(item, TypeName) and item.name == "Any"
        for item in walk_module(lowered_module)
    ):
        lowered_module = replace(
            lowered_module,
            imports=_add_import(lowered_module.imports, ImportFrom("typing", ("Any",))),
        )

    if _module_contains_literal(lowered_module):
        lowered_module = replace(
            lowered_module,
            imports=_add_import(
                lowered_module.imports, ImportFrom("typing", ("Literal",))
            ),
        )

    return Success(lowered_module)


def _replace_declaration_origins[OriginType](
    origins: tuple[GeneratedElementOrigin[OriginType], ...],
    original: Declaration,
    replacement: Declaration,
) -> tuple[GeneratedElementOrigin[OriginType], ...]:
    if isinstance(original, ClassDeclaration) and isinstance(
        replacement, ClassDeclaration
    ):
        for original_method, replacement_method in zip(
            original.methods, replacement.methods, strict=True
        ):
            origins = _replace_declaration_origins(
                origins, original_method, replacement_method
            )

    return tuple(
        GeneratedElementOrigin(item.origin, replacement)
        if item.generated is original
        else item
        for item in origins
    )


def _lower_class(
    declaration: ClassDeclaration,
    frontier: ArityFrontier,
    on_rewrite: TypeRewriteObserver | None = None,
    *,
    environment: SemanticEnvironment = (),
) -> Result[tuple[ClassDeclaration, bool], LoweringError]:
    methods: list[FunctionDeclaration | OverloadDeclaration] = []
    has_overloads = False
    for method in declaration.methods:
        if isinstance(method, OverloadDeclaration):
            methods.append(method)
            has_overloads = True
            continue

        lowered = _lower_function(
            method,
            frontier,
            on_rewrite=on_rewrite,
            environment=environment,
            reserved_type_parameters=tuple(
                type_parameter_name(parameter)
                for parameter in declaration.type_parameters
            ),
        )
        if isinstance(lowered, Failure):
            return lowered

        lowered_method = lowered.unwrap()
        methods.append(lowered_method)
        has_overloads = has_overloads or isinstance(lowered_method, OverloadDeclaration)

    return Success((replace(declaration, methods=tuple(methods)), has_overloads))


def _base_name(base: StubTypeExpression) -> str | None:
    match base:
        case TypeName(name) | TypeApplication(TypeName(name), _):
            return name
        case _:
            return None


def _lower_function(
    declaration: FunctionDeclaration,
    frontier: ArityFrontier,
    on_rewrite: TypeRewriteObserver | None = None,
    *,
    environment: SemanticEnvironment = (),
    reserved_type_parameters: tuple[str, ...] = (),
) -> Result[FunctionDeclaration | OverloadDeclaration, LoweringError]:
    if isinstance(declaration.return_type, MapType):
        return lower_map_function(
            declaration,
            declaration.return_type,
            on_rewrite=on_rewrite,
            environment=environment,
            reserved_type_parameters=reserved_type_parameters,
        )

    return lower_each_function(
        declaration,
        frontier,
        on_rewrite=on_rewrite,
        environment=environment,
        reserved_type_parameters=reserved_type_parameters,
    )


def _module_contains_literal(module: StubModule) -> bool:
    return any(
        isinstance(element, LiteralType)
        for declaration in module.declarations
        for element in walk_declaration(declaration)
    )


def _add_import(
    imports: tuple[ModuleImport, ...], required: ImportFrom
) -> tuple[ModuleImport, ...]:
    return (
        *(item for item in imports if isinstance(item, Import)),
        *sorted(
            item
            for item in merge_imports((*imports, required))
            if isinstance(item, ImportFrom)
        ),
    )
