"""Interpret concrete relationship IR through the existing static type adapter."""

from returns.result import safe

from typeforge.compiler.semantic_adapter._lowering import (
    SemanticEnvironment,
    SemanticLoweringError,
)
from typeforge.compiler.semantic_adapter._types import (
    NEVER,
    NamedType,
    ParameterizedType,
    StaticType,
    is_static,
    named_type_environment,
    union_of,
)
from typeforge.compiler.stub_ir import (
    AllPredicate,
    AnyPredicate,
    AssignablePredicate,
    CaptureType,
    ClassDeclaration,
    EqualPredicate,
    FixedTuple,
    HomogeneousTuple,
    LiteralType,
    MapType,
    NotPredicate,
    Predicate,
    RuntimeInputType,
    StubModule,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeVariable,
    UnionExpression,
    is_predicate,
    walk_type,
)
from typeforge.semantics import (
    AllExpression,
    AlternativeTypePattern,
    AnyExpression,
    AssignableExpression,
    CaptureReference,
    CaseExpression,
    EqualExpression,
    ExactTypePattern,
    Expression,
    InputReference,
    MapExpression,
    NotExpression,
    ParameterizedTypePattern,
    ParameterizedTypeTemplate,
    TypePattern,
    TypeReference,
    TypeSymbol,
    TypeValueReference,
    UnresolvedType,
)
from typeforge.semantics import UnionExpression as SemanticUnion


@safe(exceptions=(SemanticLoweringError,))
def stub_static_type(
    expression: StubTypeExpression, environment: SemanticEnvironment = ()
) -> StaticType:
    return _static_type(expression, environment)


def _static_type(
    expression: StubTypeExpression, environment: SemanticEnvironment
) -> StaticType:
    match expression:
        case TypeName("Never" | "typing.Never" | "typing_extensions.Never"):
            return NEVER
        case TypeName(name):
            bound = dict(environment).get(name)
            return bound if is_static(bound) else NamedType(name)
        case LiteralType(value):
            return ParameterizedType(NamedType("Literal"), (NamedType(repr(value)),))
        case TypeApplication(constructor, arguments):
            return ParameterizedType(
                _static_type(constructor, environment),
                tuple(_static_type(argument, environment) for argument in arguments),
            )
        case FixedTuple(items):
            tuple_items = tuple(_static_type(item, environment) for item in items)
            return ParameterizedType(NamedType("tuple"), tuple_items)
        case HomogeneousTuple(item):
            return ParameterizedType(
                NamedType("tuple"),
                (_static_type(item, environment), NamedType("...")),
            )
        case UnionExpression(members):
            return union_of(*(_static_type(member, environment) for member in members))
        case _:
            raise SemanticLoweringError(
                "a concrete input type is required for callable coverage"
            )


def stub_type_environment(module: StubModule) -> SemanticEnvironment:
    return named_type_environment(
        tuple(
            (
                declaration.name,
                (
                    *(
                        name
                        for base in declaration.bases
                        if (name := _base_name(base)) is not None
                    ),
                    *(("typing.Protocol",) if declaration.is_protocol else ()),
                ),
            )
            for declaration in module.declarations
            if isinstance(declaration, ClassDeclaration)
        )
    )


def _base_name(base: StubTypeExpression) -> str | None:
    match base:
        case TypeName(name) | TypeApplication(TypeName(name), _):
            return name
        case _:
            return None


@safe(exceptions=(SemanticLoweringError,))
def lower_stub_expression(
    expression: StubTypeExpression, environment: SemanticEnvironment = ()
) -> Expression[StaticType]:
    """Reuse shared selection and capture evaluation for retained callable IR."""
    return _stub_expression(expression, environment)


def _stub_expression(
    expression: StubTypeExpression, environment: SemanticEnvironment
) -> Expression[StaticType]:
    match expression:
        case TypeVariable(name):
            return TypeValueReference(
                UnresolvedType[StaticType](
                    NamedType(name), TypeSymbol(("callable",), name)
                )
            )
        case CaptureType(symbol):
            return CaptureReference(symbol)
        case RuntimeInputType():
            return InputReference()
        case MapType(subject, cases, default):
            return MapExpression(
                _stub_expression(subject, environment),
                tuple(
                    CaseExpression(
                        _stub_predicate(case.test, environment)
                        if is_predicate(case.test)
                        else _stub_selector(case.test, environment),
                        _stub_expression(case.output_type, environment),
                    )
                    for case in cases
                ),
                None if default is None else _stub_expression(default, environment),
            )
        case UnionExpression(members):
            return SemanticUnion(
                tuple(_stub_expression(member, environment) for member in members)
            )
        case TypeApplication(constructor, arguments):
            return ParameterizedTypeTemplate(
                _static_type(constructor, environment),
                tuple(
                    _stub_expression(argument, environment) for argument in arguments
                ),
            )
        case FixedTuple(items):
            return ParameterizedTypeTemplate(
                NamedType("tuple"),
                tuple(_stub_expression(item, environment) for item in items),
            )
        case HomogeneousTuple(item):
            return ParameterizedTypeTemplate(
                NamedType("tuple"),
                (_stub_expression(item, environment), TypeReference(NamedType("..."))),
            )
        case _:
            return TypeReference(_static_type(expression, environment))


def _stub_selector(
    expression: StubTypeExpression, environment: SemanticEnvironment
) -> Expression[StaticType] | TypePattern[StaticType]:
    if any(isinstance(item, CaptureType) for item in walk_type(expression)):
        return _stub_pattern(expression, environment)

    return _stub_expression(expression, environment)


def _stub_pattern(
    expression: StubTypeExpression, environment: SemanticEnvironment
) -> TypePattern[StaticType]:
    match expression:
        case CaptureType(symbol):
            return CaptureReference(symbol)
        case TypeVariable(name):
            return TypeValueReference(
                UnresolvedType[StaticType](
                    NamedType(name), TypeSymbol(("callable",), name)
                )
            )
        case TypeApplication(constructor, arguments):
            return ParameterizedTypePattern(
                _static_type(constructor, environment),
                tuple(_stub_pattern(argument, environment) for argument in arguments),
            )
        case FixedTuple(items):
            return ParameterizedTypePattern(
                NamedType("tuple"),
                tuple(_stub_pattern(item, environment) for item in items),
            )
        case HomogeneousTuple(item):
            return ParameterizedTypePattern(
                NamedType("tuple"),
                (_stub_pattern(item, environment), ExactTypePattern(NamedType("..."))),
            )
        case UnionExpression(members):
            return AlternativeTypePattern(
                tuple(_stub_pattern(member, environment) for member in members)
            )
        case _:
            return ExactTypePattern(_static_type(expression, environment))


def _stub_predicate(
    predicate: Predicate, environment: SemanticEnvironment
) -> Expression[StaticType]:
    match predicate:
        case EqualPredicate(left, right):
            return EqualExpression(
                _stub_expression(left, environment),
                _stub_expression(right, environment),
            )
        case AssignablePredicate(source, target):
            return AssignableExpression(
                _stub_expression(source, environment),
                _stub_expression(target, environment),
            )
        case AllPredicate(predicates):
            return AllExpression(
                tuple(_stub_predicate(item, environment) for item in predicates)
            )
        case AnyPredicate(predicates):
            return AnyExpression(
                tuple(_stub_predicate(item, environment) for item in predicates)
            )
        case NotPredicate(item):
            return NotExpression(_stub_predicate(item, environment))
