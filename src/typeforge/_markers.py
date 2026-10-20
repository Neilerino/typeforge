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

type Assignable[Source, Target] = Annotated[
    bool,
    Doc(
        "Tests whether every value described by `Source` can be assigned to "
        "`Target`. This is a static subtype-style relationship, not a runtime "
        "`isinstance` check. Use it as a Map selector, or combine it with `All`, "
        "`Any`, and `Not`.\n"
        "\n"
        "```python\n"
        "type TextResult[T] = Map[\n"
        "    T, Assignable[str] : str, ... : bytes\n"
        "]\n"
        "```"
    ),
]
type Equal[Left, Right] = Annotated[
    bool,
    Doc(
        "Tests whether `Left` and `Right` represent the same static type. Unlike "
        "`Assignable`, equality is symmetric and does not accept a proper subtype"
        " as a match. Use it as a Map selector, or combine it with `All`, `Any`, "
        "and `Not`.\n"
        "\n"
        "```python\n"
        "type BytesResult[T] = Map[\n"
        "    T, Equal[bytes] : str, ... : T\n"
        "]\n"
        "```"
    ),
]
type All[*Conditions] = Annotated[
    bool,
    Doc(
        "Combines Typeforge conditions with logical AND. `All` is true only when "
        "every supplied condition is true, and it can be nested with `Any` and "
        "`Not` to build a compound predicate.\n"
        "\n"
        "```python\n"
        "type TextResult[T] = Map[\n"
        "    T,\n"
        "    All[Assignable[str], Not[Equal[LiteralString]]] : str,\n"
        "    ... : bytes,\n"
        "]\n"
        "```"
    ),
]
type Any[*Conditions] = Annotated[
    bool,
    Doc(
        "Combines Typeforge conditions with logical OR. `Any` is true when at "
        "least one supplied condition is true, and it can be nested with `All` "
        "and `Not` to build a compound predicate.\n"
        "\n"
        "```python\n"
        "type TextResult[T] = Map[\n"
        "    T,\n"
        "    Any[Equal[str], Equal[bytes]] : str,\n"
        "    ... : T,\n"
        "]\n"
        "```"
    ),
]
type Is[Target] = Annotated[
    bool,
    Doc(
        "Matches the complete original Map subject exactly against Target. "
        "Bare selectors use Python assignment compatibility; Is preserves an "
        "exact whole-type comparison. Use one type argument inside a Map selector."
    ),
]

type Not[Condition] = Annotated[
    bool,
    Doc(
        "Negates one Typeforge condition. It is useful for excluding a specific "
        "case from a broader `Assignable`, `All`, or `Any` predicate.\n"
        "\n"
        "```python\n"
        "type TextResult[T] = Map[\n"
        "    T,\n"
        "    All[Assignable[str | bytes], Not[Equal[bytes]]] : str,\n"
        "    ... : T,\n"
        "]\n"
        "```"
    ),
]

# Canonical branch data consumed by source normalization and the runtime frontend.
# Public Map construction produces these aliases before generic substitution.
type Case[Test, Output] = Annotated[Output, Doc("Internal selected branch data.")]
type Default[Output] = Annotated[Output, Doc("Internal fallback branch data.")]
type Map[Subject, *Cases] = Annotated[
    object,
    Doc(
        "Transforms `Subject` through ordered `selector: output` branches. "
        "Bare selectors use Python assignment compatibility; Is[Type] compares "
        "the complete subject exactly. Structural patterns can capture types. "
        "The first matching branch supplies the output; `...: output` supplies a final "
        "fallback, and an omitted fallback preserves no-match/Never policy. The "
        "runtime constructor normalizes slices before generic substitution. None "
        "and empty endpoints denote the None type; string selectors require "
        "Literal. Raw slice annotations require Typeforge projection for static "
        "checking. At a callable boundary, Typeforge lowers representable cases "
        "into portable overloads. The canonical runtime alias is inert and falls "
        "back to `object` outside an interpreting integration such as Schema.\n"
        "\n"
        "```python\n"
        "def serialize[T](value: T) -> Map[\n"
        "    T,\n"
        "    int: float,\n"
        "    bytes: str,\n"
        "    ...: T,\n"
        "]: ...\n"
        "```"
    ),
]

type MapFields[Record, Transform] = Annotated[
    object,
    Doc(
        "Applies `Transform` independently to every field of `Record`. Within the"
        " transform, `Key` is bound to the current field name and `Value` to its "
        "type; the result must be `Field`, `OptionalField`, `ReadonlyField`, or "
        "`Drop`. The current compiler specializes named `TypedDict` records that "
        "are visible during generation.\n"
        "\n"
        "```python\n"
        "type JsonSafe[T] = MapFields[\n"
        "    T,\n"
        "    Field[\n"
        "        Key,\n"
        "        Map[Value, datetime : str, ... : Value],\n"
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
        "renaming—and `Type` determines the output value type.\n"
        "\n"
        "```python\n"
        "type JsonSafe[T] = MapFields[\n"
        "    T,\n"
        "    Field[Key, Map[Value, bytes : str, ... : Value]],\n"
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
        "returned conditionally from a predicate branch; using it as the entire "
        "transform drops every field.\n"
        "\n"
        "```python\n"
        "type Public[T] = MapFields[\n"
        "    T,\n"
        "    Map[\n"
        "        Key,\n"
        '        Literal["password"] : Drop,\n'
        "        ... : Field[Key, Value],\n"
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
        "`Literal` to select, rename, or drop particular fields. `Key` is invalid"
        " outside a field-map context.\n"
        "\n"
        "```python\n"
        "type WithoutPassword[T] = MapFields[\n"
        "    T,\n"
        '    Map[Key, Literal["password"] : Drop, ... : Field[Key, Value]],\n'
        "]\n"
        "```"
    ),
]
type Value = Annotated[
    object,
    Doc(
        "References the current field type inside `MapFields`. Structural "
        "patterns use explicitly declared Capture tokens.\n"
        "\n"
        "```python\n"
        "type OptionalFields[T] = MapFields[T, OptionalField[Key, Value]]\n"
        "```"
    ),
]
