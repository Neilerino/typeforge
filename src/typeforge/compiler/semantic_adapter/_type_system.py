"""Compiler adapter for backend-neutral semantic type operations."""

import ast
from dataclasses import dataclass

from returns.result import Failure, Result, Success

from typeforge.compiler.semantic_adapter._types import (
    NamedType,
    NeverType,
    ParameterizedType,
    StaticType,
    UnionType,
    union_of,
)
from typeforge.semantics import (
    ExpectedRecordSemanticError,
    GenericFamily,
    GenericType,
    ParameterizedTypeShape,
    RecordShape,
    SemanticIssue,
    UnsupportedExpressionSemanticError,
    compatible_generics,
    generic_family,
)
from typeforge.utils.error_handling import safe_result


@dataclass(frozen=True, slots=True)
class CompilerTypeSystem:
    """Interpret semantic operations over compiler-owned static types."""

    def equal(self, left: StaticType, right: StaticType) -> Result[bool, SemanticIssue]:
        return Success(_equal(left, right))

    @safe_result(errors=(SemanticIssue,))
    def assignable(self, source: StaticType, target: StaticType) -> bool:
        return _assignable(source, target)

    def union_members(
        self, value: StaticType
    ) -> Result[tuple[StaticType, ...], SemanticIssue]:
        match value:
            case NeverType():
                return Success(())

            case UnionType(members):
                return Success(members)

            case _:
                return Success((value,))

    def union(
        self, members: tuple[StaticType, ...]
    ) -> Result[StaticType, SemanticIssue]:
        return Success(union_of(*members))

    def record(
        self, value: StaticType
    ) -> Result[RecordShape[StaticType], SemanticIssue]:
        if not isinstance(value, RecordShape):
            return Failure(
                ExpectedRecordSemanticError(
                    f"{value!r} is not a supported compiler record"
                )
            )

        return Success(value)

    def inspect(
        self, value: StaticType
    ) -> Result[ParameterizedTypeShape[StaticType] | None, SemanticIssue]:
        if isinstance(value, ParameterizedType):
            return Success(ParameterizedTypeShape(value.origin, value.arguments))

        return Success(None)

    def build(
        self, shape: ParameterizedTypeShape[StaticType]
    ) -> Result[StaticType, SemanticIssue]:
        return Success(ParameterizedType(shape.origin, shape.arguments))

    @safe_result(errors=(SemanticIssue,))
    def generic_type(
        self, shape: ParameterizedTypeShape[StaticType]
    ) -> GenericType[StaticType] | None:
        if (
            not isinstance(shape.origin, NamedType)
            or generic_family(shape.origin.identity or shape.origin.name) is None
        ):
            return None

        return _generic_type(ParameterizedType(shape.origin, shape.arguments))


def _equal(left: StaticType, right: StaticType) -> bool:
    match left, right:
        case NamedType(), NamedType():
            return _type_identity(left) == _type_identity(right)
        case UnionType(left_members), UnionType(right_members):
            return all(
                any(_equal(member, candidate) for candidate in right_members)
                for member in left_members
            ) and all(
                any(_equal(member, candidate) for candidate in left_members)
                for member in right_members
            )
        case ParameterizedType(left_origin, left_args), ParameterizedType(
            right_origin, right_args
        ):
            return (
                _equal(left_origin, right_origin)
                and len(left_args) == len(right_args)
                and all(
                    _equal(a, b) for a, b in zip(left_args, right_args, strict=True)
                )
            )
        case _:
            return left == right


def _assignable(source: StaticType, target: StaticType) -> bool:
    if _equal(source, target):
        return True

    if isinstance(source, NamedType) and _type_identity(source) in {
        "Any",
        "typing.Any",
        "typing_extensions.Any",
    }:
        return True

    if isinstance(target, NamedType) and _type_identity(target) in {
        "Any",
        "typing.Any",
        "typing_extensions.Any",
    }:
        return True

    if isinstance(source, NeverType):
        return True

    if isinstance(target, NamedType) and _type_identity(target) == "object":
        return True

    if isinstance(source, UnionType):
        return all(_assignable(member, target) for member in source.members)

    if isinstance(target, UnionType):
        return any(_assignable(source, member) for member in target.members)

    if _origin_name(source) in {"Annotated", "typing.Annotated"}:
        assert isinstance(source, ParameterizedType)
        return _assignable(source.arguments[0], target)

    if _origin_name(target) in {"Annotated", "typing.Annotated"}:
        assert isinstance(target, ParameterizedType)
        return _assignable(source, target.arguments[0])

    if _origin_name(source) in {"Literal", "typing.Literal"}:
        assert isinstance(source, ParameterizedType)
        if _origin_name(target) in {"Literal", "typing.Literal"}:
            assert isinstance(target, ParameterizedType)
            return all(
                any(_equal(item, candidate) for candidate in target.arguments)
                for item in source.arguments
            )

        return all(
            _assignable(_literal_type(item), target) for item in source.arguments
        )

    if _origin_name(target) in {"Literal", "typing.Literal"}:
        return False

    match source, target:
        case ParameterizedType(), ParameterizedType():
            return compatible_generics(
                _generic_type(source), _generic_type(target), COMPILER_TYPE_SYSTEM
            )
        case NamedType(), ParameterizedType():
            if source.name in {"str", "bytes", "bytearray"} and _origin_name(
                target
            ) in {"Sequence", "typing.Sequence", "collections.abc.Sequence"}:
                raise UnsupportedExpressionSemanticError(
                    f"{source.name} is outside supported generic compatibility"
                )

            if source.name not in {
                "bool",
                "int",
                "float",
                "complex",
                "str",
                "bytes",
                "bytearray",
                "object",
                "None",
                "NoneType",
            }:
                raise UnsupportedExpressionSemanticError(
                    f"{source.name} is outside supported generic compatibility"
                )

            return False
        case NamedType(), NamedType():
            compatible_builtins = {
                "bool": {"int", "float", "complex"},
                "int": {"float", "complex"},
                "float": {"complex"},
            }
            return (
                source.name == target.name
                or target.name in source.bases
                or any(
                    target.name in compatible_builtins.get(name, set())
                    for name in (source.name, *source.bases)
                )
            )
        case _:
            return source == target


COMPILER_TYPE_SYSTEM = CompilerTypeSystem()


def _type_identity(value: NamedType) -> str:
    identity = value.identity or value.name
    if identity in {"typing.Any", "typing_extensions.Any"}:
        return "Any"

    family = generic_family(identity)
    return family.value if family is not None else identity


def _generic_type(value: ParameterizedType) -> GenericType[StaticType]:
    family = (
        generic_family(value.origin.identity or value.origin.name)
        if isinstance(value.origin, NamedType)
        else None
    )
    if family is None:
        name = value.origin.name if isinstance(value.origin, NamedType) else "origin"
        raise UnsupportedExpressionSemanticError(
            f"{name} is outside supported generic compatibility"
        )

    variadic = family is GenericFamily.TUPLE and value.arguments[-1:] == (
        NamedType("..."),
    )
    arguments = value.arguments[:-1] if variadic else value.arguments
    if family is GenericFamily.TUPLE and arguments == (NamedType("()"),):
        arguments = ()

    return GenericType(family, arguments, variadic=variadic)


def _origin_name(value: StaticType) -> str | None:
    if isinstance(value, ParameterizedType) and isinstance(value.origin, NamedType):
        return value.origin.identity or value.origin.name

    return None


def _literal_type(value: StaticType) -> NamedType:
    if isinstance(value, NamedType):
        try:
            literal: object = ast.literal_eval(value.name)
        except SyntaxError, ValueError:
            pass
        else:
            if isinstance(literal, str | bytes | bool | int | float):
                return NamedType(type(literal).__name__)

            if literal is None:
                return NamedType("None")

    raise UnsupportedExpressionSemanticError(
        "Literal argument is outside supported literal compatibility"
    )
