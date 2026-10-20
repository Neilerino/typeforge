from typing import Literal, NotRequired, ReadOnly, Required
from typing import TypedDict as TD

from typeforge import Drop, Field, Fields, Map, OptionalField, ReadonlyField, Record
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
        ... : Field[field.name, JsonValue[field.type]],
    ]
    for field in Fields[T]
)

type EveryValue[T] = All[Assignable[T, object], Not[Equal[T, None]]]

type OptionalRecord[T] = Record(
    OptionalField[field.name, field.type] for field in Fields[T]
)
type FrozenRecord[T] = Record(
    ReadonlyField[field.name, field.type] for field in Fields[T]
)


class Payload(TD, total=False):
    identifier: Required[int]
    note: NotRequired[str]
    token: ReadOnly[bytes]
    retries: OptionalField[Literal["retries"], int]
    owner: ReadonlyField[Literal["owner"], str]


class ExtendedPayload(Payload):
    active: bool
