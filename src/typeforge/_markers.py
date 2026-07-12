from typing import Annotated, Never

from typeforge._documentation import Doc

type Each[T] = Annotated[
    T,
    Doc(
        "Captures a separate `T` from each argument passed to a heterogeneous "
        "variadic parameter. `Each` must annotate a `*args` parameter, a function "
        "may contain only one `Each` parameter, and its expression must contain "
        "exactly one type variable. The captured types can be consumed by "
        "`Collect` elsewhere in the signature.\n\n"
        "```python\n"
        "def combine[T](\n"
        "    *parsers: Each[Parser[T]],\n"
        ") -> Parser[Collect[T]]: ...\n"
        "```"
    ),
]
type Collect[T] = Annotated[
    tuple[T, ...],
    Doc(
        "Collects the argument-specific types captured for `T` by `Each`, "
        "preserving their order as a heterogeneous type sequence. It may be used "
        "inside another generic type or unpacked into a tuple type. Without "
        "Typeforge specialization it safely falls back to `tuple[T, ...]`.\n\n"
        "```python\n"
        "def query[E, T](\n"
        "    *components: Each[type[T]],\n"
        ") -> tuple[E, *Collect[T]]: ...\n"
        "```"
    ),
]

type If[Condition, Then, Else] = Annotated[
    Then | Else,
    Doc(
        "Selects `Then` when a Typeforge condition is true and `Else` when it is "
        "false. Conditions are built with `Equal`, `Assignable`, `All`, `Any`, "
        "and `Not`; within `MapFields` they may also inspect `Key` and `Value`. "
        "The portable fallback is the union of both branches.\n\n"
        "```python\n"
        "def decode[T](value: T) -> If[Equal[T, bytes], str, T]: ...\n"
        "```"
    ),
]
type Assignable[Source, Target] = Annotated[
    bool,
    Doc(
        "Tests whether every value described by `Source` can be assigned to "
        "`Target`. This is a static subtype-style relationship, not a runtime "
        "`isinstance` check. Use it as a condition inside `If`, `All`, `Any`, or "
        "`Not`.\n\n"
        "```python\n"
        "type TextResult[T] = If[Assignable[T, str], str, bytes]\n"
        "```"
    ),
]
type Equal[Left, Right] = Annotated[
    bool,
    Doc(
        "Tests whether `Left` and `Right` represent the same static type. Unlike "
        "`Assignable`, equality is symmetric and does not accept a proper subtype "
        "as a match. Use it as a condition inside `If`, `All`, `Any`, or `Not`.\n\n"
        "```python\n"
        "type BytesResult[T] = If[Equal[T, bytes], str, T]\n"
        "```"
    ),
]
type All[*Conditions] = Annotated[
    bool,
    Doc(
        "Combines Typeforge conditions with logical AND. `All` is true only when "
        "every supplied condition is true, and it can be nested with `Any` and "
        "`Not` to build a compound predicate.\n\n"
        "```python\n"
        "type TextResult[T] = If[\n"
        "    All[Assignable[T, str], Not[Equal[T, LiteralString]]],\n"
        "    str,\n"
        "    bytes,\n"
        "]\n"
        "```"
    ),
]
type Any[*Conditions] = Annotated[
    bool,
    Doc(
        "Combines Typeforge conditions with logical OR. `Any` is true when at "
        "least one supplied condition is true, and it can be nested with `All` "
        "and `Not` to build a compound predicate.\n\n"
        "```python\n"
        "type TextResult[T] = If[\n"
        "    Any[Equal[T, str], Equal[T, bytes]],\n"
        "    str,\n"
        "    T,\n"
        "]\n"
        "```"
    ),
]
type Not[Condition] = Annotated[
    bool,
    Doc(
        "Negates one Typeforge condition. It is useful for excluding a specific "
        "case from a broader `Assignable`, `All`, or `Any` predicate.\n\n"
        "```python\n"
        "type TextResult[T] = If[\n"
        "    All[Assignable[T, str | bytes], Not[Equal[T, bytes]]],\n"
        "    str,\n"
        "    T,\n"
        "]\n"
        "```"
    ),
]

type Case[Input, Output] = Annotated[
    Output,
    Doc(
        "Defines one input-to-output branch inside `Map`. Cases are tested in "
        "declaration order and the first exact match wins. A structural input such "
        "as `Option[Value]` can capture its nested type and reuse that `Value` in "
        "the output.\n\n"
        "```python\n"
        "type QueryResult[T] = Map[\n"
        "    T,\n"
        "    Case[Option[Value], Value | None],\n"
        "    Default[T],\n"
        "]\n"
        "```"
    ),
]
type Default[Output] = Annotated[
    Output,
    Doc(
        "Defines the fallback output of a `Map` when no `Case` matches. If a map "
        "does not contain `Default`, its unmatched result is `Never`.\n\n"
        "```python\n"
        "type Encoded[T] = Map[\n"
        "    T,\n"
        "    Case[bytes, str],\n"
        "    Default[T],\n"
        "]\n"
        "```"
    ),
]
type Map[Subject, *Cases] = Annotated[
    object,
    Doc(
        "Transforms `Subject` through an ordered sequence of `Case` branches. "
        "The first exact or structural match supplies the output; `Default` is "
        "used when none match, and an omitted default produces `Never`. At a "
        "callable boundary, Typeforge lowers finite cases into portable overloads.\n\n"
        "```python\n"
        "def serialize[T](value: T) -> Map[\n"
        "    T,\n"
        "    Case[int, float],\n"
        "    Case[bytes, str],\n"
        "    Default[T],\n"
        "]: ...\n"
        "```"
    ),
]

type MapFields[Record, Transform] = Annotated[
    object,
    Doc(
        "Applies `Transform` independently to every field of `Record`. Within the "
        "transform, `Key` is bound to the current field name and `Value` to its "
        "type; the result must be `Field`, `OptionalField`, `ReadonlyField`, or "
        "`Drop`. The current compiler specializes named `TypedDict` records that "
        "are visible during generation.\n\n"
        "```python\n"
        "type JsonSafe[T] = MapFields[\n"
        "    T,\n"
        "    Field[\n"
        "        Key,\n"
        "        Map[Value, Case[datetime, str], Default[Value]],\n"
        "    ],\n"
        "]\n"
        "```"
    ),
]
type Field[Name, Type] = Annotated[
    Type,
    Doc(
        "Emits a required, writable field from a `MapFields` transform. `Name` "
        "determines the output key—normally `Key`, or a string `Literal` when "
        "renaming—and `Type` determines the output value type.\n\n"
        "```python\n"
        "type JsonSafe[T] = MapFields[\n"
        "    T,\n"
        "    Field[Key, Map[Value, Case[bytes, str], Default[Value]]],\n"
        "]\n"
        "```"
    ),
]
type OptionalField[Name, Type] = Annotated[
    Type,
    Doc(
        "Emits a non-required, writable field from a `MapFields` transform. It "
        "uses the same output name and type arguments as `Field`, but the "
        "generated `TypedDict` key is wrapped in `NotRequired`.\n\n"
        "```python\n"
        "type Partial[T] = MapFields[\n"
        "    T,\n"
        "    OptionalField[Key, Value],\n"
        "]\n"
        "```"
    ),
]
type ReadonlyField[Name, Type] = Annotated[
    Type,
    Doc(
        "Emits a required, read-only field from a `MapFields` transform. It uses "
        "the same output name and type arguments as `Field`, but the generated "
        "`TypedDict` value is wrapped in `ReadOnly`.\n\n"
        "```python\n"
        "type Frozen[T] = MapFields[\n"
        "    T,\n"
        "    ReadonlyField[Key, Value],\n"
        "]\n"
        "```"
    ),
]
type Drop = Annotated[
    Never,
    Doc(
        "Removes the current field from a `MapFields` result. `Drop` is commonly "
        "returned conditionally from `If`; using it as the entire transform drops "
        "every field.\n\n"
        "```python\n"
        "type Public[T] = MapFields[\n"
        "    T,\n"
        "    If[\n"
        '        Equal[Key, Literal["password"]],\n'
        "        Drop,\n"
        "        Field[Key, Value],\n"
        "    ],\n"
        "]\n"
        "```"
    ),
]
type Key = Annotated[
    str,
    Doc(
        "References the current field name while evaluating a `MapFields` "
        "transform. Use it as an output name, or compare it with a string "
        "`Literal` to select, rename, or drop particular fields. `Key` is invalid "
        "outside a field-map context.\n\n"
        "```python\n"
        "type WithoutPassword[T] = MapFields[\n"
        "    T,\n"
        '    If[Equal[Key, Literal["password"]], Drop, Field[Key, Value]],\n'
        "]\n"
        "```"
    ),
]
type Value = Annotated[
    object,
    Doc(
        "References a type captured by the surrounding transformation. Inside "
        "`MapFields`, it is the current field type. Inside a structural `Case` "
        "such as `Option[Value]`, it is the nested generic argument matched from "
        "the map subject.\n\n"
        "```python\n"
        "type QueryResult[T] = Map[\n"
        "    T,\n"
        "    Case[Option[Value], Value | None],\n"
        "    Default[T],\n"
        "]\n"
        "```"
    ),
]
