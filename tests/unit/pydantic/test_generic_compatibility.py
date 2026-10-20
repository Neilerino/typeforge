from typing import get_args, get_origin

import pytest
from returns.result import Failure

from typeforge.pydantic._type_system import RUNTIME_TYPE_SYSTEM, concrete_type
from typeforge.semantics import (
    GenericFamily,
    GenericType,
    ParameterizedTypeShape,
    UnsupportedExpressionSemanticError,
)


@pytest.mark.parametrize(
    ("annotation", "family", "arguments", "variadic"),
    [
        (list[int], GenericFamily.LIST, (int,), False),
        (tuple[int, str], GenericFamily.TUPLE, (int, str), False),
        (tuple[int, ...], GenericFamily.TUPLE, (int,), True),
        (tuple[()], GenericFamily.TUPLE, (), False),
    ],
)
def test_generic_facts_preserve_family_and_normalize_tuple_markers(
    annotation: object,
    family: GenericFamily,
    arguments: tuple[object, ...],
    variadic: bool,
) -> None:
    shape = ParameterizedTypeShape(
        concrete_type(get_origin(annotation)),
        tuple(concrete_type(argument) for argument in get_args(annotation)),
    )

    assert RUNTIME_TYPE_SYSTEM.generic_type(shape).unwrap() == GenericType(
        family,
        tuple(concrete_type(argument) for argument in arguments),
        variadic=variadic,
    )


def test_unsupported_generic_is_unknown_to_inspection_but_fails_comparison() -> None:
    class Opaque[T]:
        pass

    source = concrete_type(Opaque[int])
    target = concrete_type(Opaque[str])
    shape = RUNTIME_TYPE_SYSTEM.inspect(source).unwrap()
    assert shape is not None
    assert RUNTIME_TYPE_SYSTEM.generic_type(shape).unwrap() is None

    result = RUNTIME_TYPE_SYSTEM.assignable(source, target)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), UnsupportedExpressionSemanticError)
    assert RUNTIME_TYPE_SYSTEM.assignable(source, source).unwrap() is True
