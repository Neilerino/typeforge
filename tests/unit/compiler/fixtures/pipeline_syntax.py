from datetime import datetime
from typing import Literal, TypedDict

from typeforge import Field, Fields, Map, Record
from typeforge._markers import Equal


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


type JsonSafe[T] = Record(
    Field(name=field.name, type=Map[field.type, datetime:str, ... : field.type])
    for field in Fields[T]
)


def jsonify[T](value: T) -> JsonSafe[T]:
    raise NotImplementedError
