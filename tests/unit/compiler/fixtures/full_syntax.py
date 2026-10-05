from typing import Literal, NotRequired, ReadOnly, Required
from typing import TypedDict as TD

from typeforge import Drop, Field, Fields, Map, Record
from typeforge._markers import All, Assignable, Equal, Not
from typeforge._markers import Any as AnyCondition

type JsonValue[T] = Map[
    T,
    bytes:str,
    int:float,
    ...:T,
]

type PublicRecord[T] = Record(
    Map[
        field.name,
        AnyCondition[
            Equal[field.name, Literal["password"]], Not[Assignable[field.type, object]]
        ] : Drop,
        ... : Field(name=field.name, type=JsonValue[field.type]),
    ]
    for field in Fields[T]
)

type EveryValue[T] = All[Assignable[T, object], Not[Equal[T, None]]]

type OptionalRecord[T] = Record(
    Field(name=field.name, type=field.type, required=False) for field in Fields[T]
)
type FrozenRecord[T] = Record(
    Field(name=field.name, type=field.type, readonly=True) for field in Fields[T]
)


class Payload(TD, total=False):
    identifier: Required[int]
    note: NotRequired[str]
    token: ReadOnly[bytes]
    retries: NotRequired[int]
    owner: ReadOnly[str]


class ExtendedPayload(Payload):
    active: bool
