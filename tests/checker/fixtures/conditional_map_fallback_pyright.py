from typing import assert_type

from typeforge import All, Any, Assignable, Case, Default, Equal, If, Map, Not

type Serialized[T] = Map[
    T,
    Case[int, float],
    Case[bytes, str],
    Default[T],
]


def normalize[T](value: T) -> If[Assignable[T, str], str, bytes]:
    raise NotImplementedError


def serialize[T](value: T) -> Serialized[T]:
    raise NotImplementedError


def classify[T](
    value: T,
) -> If[
    All[Assignable[T, object], Not[Equal[T, bytes]]],
    int,
    If[Any[Equal[T, bytes], Equal[T, str]], str, bytes],
]:
    raise NotImplementedError


assert_type(normalize("value"), str | bytes)
assert_type(serialize(1), object)
assert_type(classify("value"), int | str | bytes)
