from datetime import datetime
from typing import Literal, TypedDict

from typeforge import (
    Case,
    Collect,
    Default,
    Each,
    Equal,
    Field,
    If,
    Key,
    Map,
    MapFields,
    Value,
)


def collect[T](*values: Each[T]) -> Collect[T]:
    return values


def read[M](mode: M) -> If[Equal[M, Literal["text"]], str, bytes]:
    raise NotImplementedError


def serialize[T](
    value: T,
) -> Map[
    T,
    Case[int, float],
    Case[datetime, str],
    Default[T],
]:
    raise NotImplementedError


class User(TypedDict):
    name: str
    created_at: datetime


class Post(TypedDict):
    title: str


type JsonSafe[T] = MapFields[
    T,
    Field[
        Key,
        Map[Value, Case[datetime, str], Default[Value]],
    ],
]


def jsonify[T](value: T) -> JsonSafe[T]:
    raise NotImplementedError
