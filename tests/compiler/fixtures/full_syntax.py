from typing import Literal, NotRequired, ReadOnly, Required
from typing import TypedDict as TD

from typeforge import (
    All,
    Assignable,
    Case,
    Default,
    Drop,
    Equal,
    Field,
    If,
    Key,
    Map,
    MapFields,
    Not,
    OptionalField,
    ReadonlyField,
    Value,
)
from typeforge import (
    Any as AnyCondition,
)

type JsonValue[T] = Map[
    T,
    Case[bytes, str],
    Case[int, float],
    Default[T],
]

type PublicRecord[T] = MapFields[
    T,
    If[
        AnyCondition[
            Equal[Key, Literal["password"]],
            Not[Assignable[Value, object]],
        ],
        Drop,
        Field[Key, JsonValue[Value]],
    ],
]

type EveryValue[T] = All[Assignable[T, object], Not[Equal[T, None]]]

type OptionalRecord[T] = MapFields[T, OptionalField[Key, Value]]
type FrozenRecord[T] = MapFields[T, ReadonlyField[Key, Value]]


class Payload(TD, total=False):
    identifier: Required[int]
    note: NotRequired[str]
    token: ReadOnly[bytes]
    retries: OptionalField[Literal["retries"], int]
    owner: ReadonlyField[Literal["owner"], str]


class ExtendedPayload(Payload):
    active: bool
