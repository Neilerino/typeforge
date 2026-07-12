from datetime import datetime
from typing import Literal, TypedDict

from typeforge import (
    Case,
    Default,
    Equal,
    Field,
    If,
    Key,
    Map,
    MapFields,
    Value,
)


def read[M](mode: M) -> If[Equal[M, Literal["text"]], str, bytes]:
    raise NotImplementedError


def serialize[T](
    value: T,
) -> Map[
    T,
    Case[int, float],
    Case[bytes, str],
    Default[T],
]:
    raise NotImplementedError


def strict_serialize[T](value: T) -> Map[T, Case[int, str]]:
    raise NotImplementedError


class User(TypedDict):
    name: str
    created_at: datetime
    attempts: int


type JsonSafe[T] = MapFields[
    T,
    Field[
        Key,
        Map[Value, Case[datetime, str], Default[Value]],
    ],
]


def jsonify[T](value: T) -> JsonSafe[T]:
    raise NotImplementedError
