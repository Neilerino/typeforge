from datetime import datetime
from typing import Literal, TypedDict

from typeforge import Collect, Each, Field, Fields, Is, Map, Record


def collect[T](*values: Each[T]) -> Collect[T]:
    return values


def read[M](
    mode: M,
) -> Map[
    M,
    Is[Literal["text"]] : str,
    ...:bytes,
]:
    raise NotImplementedError


def serialize[T](
    value: T,
) -> Map[
    T,
    int:float,
    datetime:str,
    ...:T,
]:
    raise NotImplementedError


class User(TypedDict):
    name: str
    created_at: datetime


class Post(TypedDict):
    title: str


type JsonSafe[T] = Record(
    Field(name=field.name, type=Map[field.type, datetime:str, ... : field.type])
    for field in Fields[T]
)


def jsonify[T](value: T) -> JsonSafe[T]:
    raise NotImplementedError
