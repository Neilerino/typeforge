"""Python typing operations behind the shared TypeSystem interface."""

from dataclasses import dataclass
from operator import getitem
from typing import Any, Literal, Never, Protocol, Union, cast, get_args, get_origin

from returns.result import Failure, Result, Success

from typeforge.semantics import (
    ParameterizedTypeShape,
    RecordShape,
    SemanticAdapterError,
    SemanticIssue,
)
from typeforge.utils.error_handling import safe_result


@dataclass(frozen=True, slots=True)
class RuntimeType:
    """Effective semantic type and the annotation delegated to Pydantic.

    A fallback may compare as its bound while retaining the original TypeVar
    for Pydantic's distinct validation and serialization behavior.
    """

    value: object
    annotation: object


def concrete_type(value: object) -> RuntimeType:
    return RuntimeType(value, value)


class _Subscriptable(Protocol):
    def __getitem__(self, arguments: tuple[object, ...], /) -> object: ...


def _members(value: object) -> tuple[object, ...]:
    if value is Never:
        return ()

    return get_args(value) if get_origin(value) is Union else (value,)


def _union(values: tuple[object, ...]) -> object:
    members: list[object] = []
    for value in values:
        for member in _members(value):
            if member is Any:
                return Any

            if member not in members:
                members.append(member)

    if not members:
        return Never

    result = (
        members[0]
        if len(members) == 1
        else getitem(cast(_Subscriptable, Union), tuple(members))
    )
    return result


def _assignable(source: object, target: object) -> bool:
    if source is Never or target is Any or target is object or source == target:
        return True

    if get_origin(source) is Union:
        return all(_assignable(member, target) for member in get_args(source))

    if get_origin(target) is Union:
        return any(_assignable(source, member) for member in get_args(target))

    if get_origin(source) is Literal:
        values: tuple[object, ...] = get_args(source)
        return all(_assignable(type(value), target) for value in values)

    if get_origin(target) is Literal:
        return False

    source_origin, target_origin = get_origin(source), get_origin(target)
    source_class, target_class = source_origin or source, target_origin or target
    if isinstance(source_class, type) and isinstance(target_class, type):
        try:
            matches = issubclass(source_class, target_class)
        except TypeError:
            return False

        return matches and (
            source_origin != target_origin
            or not get_args(target)
            or get_args(source) == get_args(target)
        )

    return False


class RuntimeTypeSystem:
    def equal(
        self, left: RuntimeType, right: RuntimeType
    ) -> Result[bool, SemanticIssue]:
        return Success(left.value == right.value)

    def assignable(
        self, source: RuntimeType, target: RuntimeType
    ) -> Result[bool, SemanticIssue]:
        return Success(_assignable(source.value, target.value))

    def union_members(
        self, value: RuntimeType
    ) -> Result[tuple[RuntimeType, ...], SemanticIssue]:
        if value.value is Never:
            return Success(())

        if get_origin(value.value) is not Union:
            return Success((value,))

        return Success(tuple(concrete_type(member) for member in get_args(value.value)))

    def union(
        self, members: tuple[RuntimeType, ...]
    ) -> Result[RuntimeType, SemanticIssue]:
        return Success(
            RuntimeType(
                _union(tuple(member.value for member in members)),
                _union(tuple(member.annotation for member in members)),
            )
        )

    def record(
        self, value: RuntimeType
    ) -> Result[RecordShape[RuntimeType], SemanticIssue]:
        return Failure(SemanticAdapterError("Record adaptation is not available yet"))

    def inspect(
        self, value: RuntimeType
    ) -> Result[ParameterizedTypeShape[RuntimeType] | None, SemanticIssue]:
        origin = get_origin(value.value)
        if origin is None:
            return Success(None)

        return Success(
            ParameterizedTypeShape(
                concrete_type(origin),
                tuple(concrete_type(argument) for argument in get_args(value.value)),
            )
        )

    @safe_result(errors=(SemanticIssue,))
    def build(self, shape: ParameterizedTypeShape[RuntimeType]) -> RuntimeType:
        def construct(origin: object, arguments: tuple[object, ...]) -> object:
            if origin is Union:
                return _union(arguments)

            try:
                # Runtime typing subscription can use metaclass or class hooks
                # that cannot be expressed by the object's static type.
                result = getitem(cast(_Subscriptable, origin), arguments)
            except (TypeError, ValueError) as error:
                raise SemanticAdapterError(
                    f"Cannot rebuild {origin!r} with {arguments!r}: {error}"
                ) from error

            return result

        return RuntimeType(
            construct(shape.origin.value, tuple(arg.value for arg in shape.arguments)),
            construct(
                shape.origin.annotation,
                tuple(arg.annotation for arg in shape.arguments),
            ),
        )


RUNTIME_TYPE_SYSTEM = RuntimeTypeSystem()
