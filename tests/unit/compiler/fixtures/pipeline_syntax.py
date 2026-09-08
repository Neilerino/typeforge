from datetime import datetime
from typing import Literal, TypedDict

from typeforge import Equal, Field, Key, Map, MapFields, Value


def read[M](
    mode: M,
) -> Map[
    M,
    Equal[M, Literal["text"]] : str,
    ...:bytes,
]:
    raise NotImplementedError


def serialize[T](
    value: T,
) -> Map[
    T,
    int:float,
    bytes:str,
    ...:T,
]:
    raise NotImplementedError


def strict_serialize[T](value: T) -> Map[T, int:str]:
    raise NotImplementedError


class User(TypedDict):
    name: str
    created_at: datetime
    attempts: int


type JsonSafe[T] = MapFields[
    T,
    Field[
        Key,
        Map[Value, datetime:str, ...:Value],
    ],
]


def jsonify[T](value: T) -> JsonSafe[T]:
    raise NotImplementedError
