from typing import assert_type

from typeforge import All, Any, Assignable, Case, Default, Equal, Map, Not

type Serialized[T] = Map[
    T,
    Case[int, float],
    Case[bytes, str],
    Default[T],
]


def normalize[T](value: T) -> Map[T, Case[Assignable[T, str], str], Default[bytes]]:
    raise NotImplementedError


def serialize[T](value: T) -> Serialized[T]:
    raise NotImplementedError


def classify[T](
    value: T,
) -> Map[
    T,
    Case[All[Assignable[T, object], Not[Equal[T, bytes]]], int],
    Default[
        Map[
            T,
            Case[Any[Equal[T, bytes], Equal[T, str]], str],
            Default[bytes],
        ]
    ],
]:
    raise NotImplementedError


assert_type(normalize("value"), object)
assert_type(serialize(1), object)
assert_type(classify("value"), object)
