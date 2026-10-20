"""Project no-default input domains without admitting known uncovered types."""

from returns.result import Result

from typeforge.compiler.semantic_adapter import (
    COMPILER_TYPE_SYSTEM,
    NamedType,
    SemanticEnvironment,
    SemanticLoweringError,
    StaticType,
    UnionType,
    stub_static_type,
    union_of,
)
from typeforge.compiler.specialization._bounds import checker_type_bound
from typeforge.compiler.specialization._captures import capture_tokens
from typeforge.compiler.specialization._models import LoweringError, LoweringErrorCode
from typeforge.compiler.stub_ir import (
    AssignablePredicate,
    CaptureType,
    EqualPredicate,
    FunctionDeclaration,
    LiteralType,
    MapCase,
    MapType,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeRewriteObserver,
    TypeVariable,
    UnionExpression,
    is_predicate,
    substitute_type,
    union_types,
    walk_type,
)
from typeforge.semantics import SemanticIssue
from typeforge.utils.error_handling import safe_result

_COVERAGE_ERRORS: tuple[type[SemanticIssue | SemanticLoweringError], ...] = (
    SemanticIssue,
    SemanticLoweringError,
)


def map_input_domain(
    declaration: FunctionDeclaration,
    mapping: MapType,
    controller: str,
    environment: SemanticEnvironment = (),
) -> Result[StubTypeExpression, LoweringError]:
    return _input_domain(declaration, mapping, controller, environment).alt(
        lambda error: _coverage_error(declaration, error)
    )


def map_covered_cases(
    declaration: FunctionDeclaration,
    mapping: MapType,
    controller: str,
    domain: StubTypeExpression,
    environment: SemanticEnvironment = (),
) -> Result[tuple[MapCase, ...], LoweringError]:
    return _covered_cases(mapping, controller, domain, environment).alt(
        lambda error: _coverage_error(declaration, error)
    )


def map_output_bound(
    declaration: FunctionDeclaration,
    mapping: MapType,
    controller: str,
    domain: StubTypeExpression,
    replacement: StubTypeExpression,
    environment: SemanticEnvironment = (),
    *,
    on_rewrite: TypeRewriteObserver | None = None,
) -> Result[StubTypeExpression, LoweringError]:
    return _output_bound(
        mapping, controller, domain, replacement, environment, on_rewrite
    ).alt(lambda error: _coverage_error(declaration, error))


def map_case_input(
    declaration: FunctionDeclaration,
    controller: str,
    pattern: StubTypeExpression,
    environment: SemanticEnvironment,
) -> Result[StubTypeExpression | None, LoweringError]:
    return _case_input(declaration, controller, pattern, environment).alt(
        lambda error: _coverage_error(declaration, error)
    )


@safe_result(errors=_COVERAGE_ERRORS)
def _case_input(
    declaration: FunctionDeclaration,
    controller: str,
    pattern: StubTypeExpression,
    environment: SemanticEnvironment,
) -> StubTypeExpression | None:
    original = dict(declaration.type_parameter_domains).get(controller)
    if original is None:
        return pattern

    native_pattern = checker_type_bound(pattern, invariant=True)
    if _domain_contained(native_pattern, original, environment):
        return pattern

    if _domain_contained(original, native_pattern, environment):
        return original

    return None


def map_case_covers_domain(
    declaration: FunctionDeclaration,
    controller: str,
    pattern: StubTypeExpression,
    environment: SemanticEnvironment,
) -> Result[bool, LoweringError]:
    return _case_covers_domain(declaration, controller, pattern, environment).alt(
        lambda error: _coverage_error(declaration, error)
    )


def map_default_reachable(
    declaration: FunctionDeclaration,
    mapping: MapType,
    controller: str,
    environment: SemanticEnvironment,
) -> Result[bool, LoweringError]:
    return _default_reachable(declaration, mapping, controller, environment).alt(
        lambda error: _coverage_error(declaration, error)
    )


@safe_result(errors=_COVERAGE_ERRORS)
def _default_reachable(
    declaration: FunctionDeclaration,
    mapping: MapType,
    controller: str,
    environment: SemanticEnvironment,
) -> bool:
    domain = dict(declaration.type_parameter_domains).get(
        controller, TypeName("object")
    )
    covered: list[StubTypeExpression] = []
    for case in mapping.cases:
        if isinstance(case.test, CaptureType):
            return False

        candidate = _case_domain(case, controller)
        if candidate is None or capture_tokens(candidate):
            continue

        # Generic parameter shapes cannot establish coverage of native
        # subclasses whose original identity lacks matching argument facts.
        if any(isinstance(item, TypeApplication) for item in walk_type(candidate)):
            continue

        _require_native_coverage(candidate, environment)
        covered.append(candidate)
        if _domain_contained(domain, union_types(tuple(covered)), environment):
            return False

    return True


@safe_result(errors=_COVERAGE_ERRORS)
def _case_covers_domain(
    declaration: FunctionDeclaration,
    controller: str,
    pattern: StubTypeExpression,
    environment: SemanticEnvironment,
) -> bool:
    original = dict(declaration.type_parameter_domains).get(controller)
    return original is not None and _domain_contained(
        original, checker_type_bound(pattern, invariant=True), environment
    )


def _coverage_error(
    declaration: FunctionDeclaration, error: SemanticIssue | SemanticLoweringError
) -> LoweringError:
    return LoweringError(
        LoweringErrorCode.UNREPRESENTABLE_COVERAGE,
        declaration.name,
        f"{error.message}; supply an authored bound, explicit specialization, "
        "or fallback",
    )


@safe_result(errors=_COVERAGE_ERRORS)
def _input_domain(
    declaration: FunctionDeclaration,
    mapping: MapType,
    controller: str,
    environment: SemanticEnvironment,
) -> StubTypeExpression:
    covered = _case_domains(mapping, controller)
    for item in covered:
        stub_static_type(item, environment).unwrap()
        _require_native_coverage(item, environment)

    if not covered:
        raise SemanticLoweringError("Map input coverage cannot be represented")

    domain = union_types(tuple(covered))
    original = dict(declaration.type_parameter_domains).get(controller)
    if original is not None:
        return _intersection(original, domain, environment)

    if controller not in declaration.type_parameters:
        raise SemanticLoweringError("an enclosing type parameter needs a covered bound")

    return domain


def _require_native_coverage(
    expression: StubTypeExpression, environment: SemanticEnvironment
) -> None:
    for item in walk_type(expression):
        if not isinstance(item, TypeName):
            continue

        value = stub_static_type(item, environment).unwrap()
        if isinstance(value, NamedType) and any(
            name not in dict(environment)
            and name.rsplit(".", 1)[-1] in {"TypedDict", "Protocol"}
            for name in (value.name, *value.bases)
        ):
            raise SemanticLoweringError(
                "structural input coverage requires matching structural type facts"
            )


def _case_domains(mapping: MapType, controller: str) -> tuple[StubTypeExpression, ...]:
    return tuple(
        domain
        for case in mapping.cases
        if (domain := _case_domain(case, controller)) is not None
    )


def _case_domain(case: MapCase, controller: str) -> StubTypeExpression | None:
    match case.test:
        case TypeVariable(name) if name == controller:
            return TypeName("object")
        case AssignablePredicate(TypeVariable(name), target) if name == controller:
            return target
        case EqualPredicate(TypeVariable(name), TypeVariable(target)) if (
            name == target == controller
        ):
            return TypeName("object")
        case EqualPredicate(TypeVariable(name), LiteralType()) if name == controller:
            return case.test.right
        case EqualPredicate(
            TypeVariable(name), TypeApplication(TypeName("Literal"), _)
        ) if name == controller:
            return case.test.right
        case EqualPredicate(TypeVariable(name), TypeName("None" | "NoneType")) if (
            name == controller
        ):
            return TypeName("None")
        case test if not is_predicate(test):
            return test
        case _:
            return None


def _domain_contained(
    source: StubTypeExpression,
    target: StubTypeExpression,
    environment: SemanticEnvironment,
) -> bool:
    if _contains_any(source) and not _contains_any(target):
        if target == TypeName("object"):
            return True

        if any(
            isinstance(item, TypeApplication) and _contains_any(item)
            for item in walk_type(source)
        ):
            return False

    return COMPILER_TYPE_SYSTEM.assignable(
        _native_domain(stub_static_type(source, environment).unwrap()),
        _native_domain(stub_static_type(target, environment).unwrap()),
    ).unwrap()


def _contains_any(expression: StubTypeExpression) -> bool:
    return any(
        isinstance(item, TypeName)
        and item.name in {"Any", "typing.Any", "typing_extensions.Any"}
        for item in walk_type(expression)
    )


def _native_domain(value: StaticType) -> StaticType:
    match value:
        case NamedType(name) if name in {"Any", "typing.Any", "typing_extensions.Any"}:
            # A parameter annotated Any admits all statically known input types.
            # This containment proof is different from matching a known Any subject.
            return NamedType("object")
        case UnionType(members):
            return union_of(*(_native_domain(member) for member in members))
        case _:
            return value


def _intersection(
    left: StubTypeExpression,
    right: StubTypeExpression,
    environment: SemanticEnvironment,
) -> StubTypeExpression:
    if _domain_contained(left, right, environment):
        return left

    if _domain_contained(right, left, environment):
        return right

    left_members = left.members if isinstance(left, UnionExpression) else (left,)
    right_members = right.members if isinstance(right, UnionExpression) else (right,)
    members: list[StubTypeExpression] = []
    for source in left_members:
        for target in right_members:
            if _domain_contained(source, target, environment):
                members.append(source)
            elif _domain_contained(target, source, environment):
                members.append(target)

    if not members:
        raise SemanticLoweringError(
            "the authored type bound has no covered input domain"
        )

    return union_types(tuple(members))


@safe_result(errors=_COVERAGE_ERRORS)
def _covered_cases(
    mapping: MapType,
    controller: str,
    domain: StubTypeExpression,
    environment: SemanticEnvironment,
) -> tuple[MapCase, ...]:
    cases: list[MapCase] = []
    for candidate in _case_domains(mapping, controller):
        if _domain_contained(domain, candidate, environment):
            input_type = domain
        elif _domain_contained(candidate, domain, environment):
            input_type = candidate
        else:
            continue

        if any(
            not is_predicate(case.test)
            and _domain_contained(input_type, case.test, environment)
            for case in cases
        ):
            continue

        cases.append(
            MapCase(
                input_type,
                _possible_outputs(
                    mapping, controller, input_type, input_type, environment
                ),
            )
        )

    if _checker_literal_collision(tuple(cases)):
        return (
            MapCase(
                domain,
                _possible_outputs(mapping, controller, domain, domain, environment),
            ),
        )

    return tuple(cases)


def _checker_literal_collision(cases: tuple[MapCase, ...]) -> bool:
    spellings = {
        spelling
        for case in cases
        if not is_predicate(case.test)
        for spelling in _literal_spellings(case.test)
    }
    # Mypy treats these overload domains as overlapping even though Map keeps
    # the bool and int literals distinct. An aggregate signature stays portable.
    return {"True", "1"} <= spellings or {"False", "0"} <= spellings


def _literal_spellings(expression: StubTypeExpression) -> tuple[str, ...]:
    match expression:
        case LiteralType(value):
            return (repr(value),)
        case TypeApplication(TypeName("Literal" | "typing.Literal"), arguments):
            return tuple(item.name for item in arguments if isinstance(item, TypeName))
        case UnionExpression(members):
            return tuple(
                spelling
                for member in members
                for spelling in _literal_spellings(member)
            )
        case _:
            return ()


@safe_result(errors=_COVERAGE_ERRORS)
def _output_bound(
    mapping: MapType,
    controller: str,
    domain: StubTypeExpression,
    replacement: StubTypeExpression,
    environment: SemanticEnvironment,
    on_rewrite: TypeRewriteObserver | None,
) -> StubTypeExpression:
    return _possible_outputs(
        mapping, controller, domain, replacement, environment, on_rewrite
    )


def _possible_outputs(
    mapping: MapType,
    controller: str,
    domain: StubTypeExpression,
    replacement: StubTypeExpression,
    environment: SemanticEnvironment,
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    outputs: list[StubTypeExpression] = []
    covered: list[StubTypeExpression] = []
    exhausted = False
    for case in mapping.cases:
        candidate = _case_domain(case, controller)
        if candidate is None:
            # Exact and compound conditions can refine a covered range without
            # making that whole range an accepted input domain.
            outputs.append(
                substitute_type(
                    case.output_type, controller, replacement, on_rewrite=on_rewrite
                )
            )
            continue

        overlaps = _domain_contained(
            domain, candidate, environment
        ) or _domain_contained(candidate, domain, environment)
        if overlaps or _may_overlap(domain, candidate):
            outputs.append(
                substitute_type(
                    case.output_type, controller, replacement, on_rewrite=on_rewrite
                )
            )

        if overlaps:
            covered.append(candidate)

        if covered and _domain_contained(
            domain, union_types(tuple(covered)), environment
        ):
            exhausted = True
            break

    if not exhausted and mapping.default is not None:
        outputs.append(
            substitute_type(
                mapping.default, controller, replacement, on_rewrite=on_rewrite
            )
        )

    return union_types(tuple(outputs))


def _may_overlap(left: StubTypeExpression, right: StubTypeExpression) -> bool:
    left_members = left.members if isinstance(left, UnionExpression) else (left,)
    right_members = right.members if isinstance(right, UnionExpression) else (right,)
    builtins = {
        "bool",
        "int",
        "float",
        "complex",
        "str",
        "bytes",
        "bytearray",
        "None",
        "NoneType",
        "object",
        "Any",
        "typing.Any",
        "typing_extensions.Any",
        "Never",
    }
    for source in left_members:
        for target in right_members:
            if _is_literal(source) and _is_literal(target):
                continue

            if isinstance(source, TypeName) and isinstance(target, TypeName):
                if source.name in {"bool", "None", "NoneType", "Never"} or (
                    target.name in {"bool", "None", "NoneType", "Never"}
                ):
                    continue

                if source.name not in builtins or target.name not in builtins:
                    # A future subclass may satisfy otherwise unrelated bases.
                    return True

            if isinstance(source, TypeApplication) or isinstance(
                target, TypeApplication
            ):
                return True

    return False


def _is_literal(expression: StubTypeExpression) -> bool:
    return isinstance(expression, LiteralType) or (
        isinstance(expression, TypeApplication)
        and expression.constructor in (TypeName("Literal"), TypeName("typing.Literal"))
    )
