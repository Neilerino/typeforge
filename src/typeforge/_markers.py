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

type Field[Name, Type] = Annotated[
    Type,
    Doc(
        "Emits a required, writable field into a `Record`. `Name` determines "
        "the output key, using a scoped field.name or a string Literal when "
        "renaming, and `Type` determines the value type. Whole-field passthrough "
        "preserves the source flags instead.\n"
        "\n"
        "```python\n"
        "type JsonSafe[T] = Record(\n"
        "    Field[field.name, Map[field.type, bytes: str, ...: field.type]]\n"
        "    for field in Fields[T]\n"
        ")\n"
        "```"
    ),
]
type OptionalField[Name, Type] = Annotated[
    Type,
    Doc(
        "Emits a non-required, writable field into a `Record`. It "
        "uses the same output name and type arguments as `Field`, but the "
        "generated `TypedDict` key is wrapped in `NotRequired`.\n\n"
        "```python\n"
        "type Partial[T] = Record(\n"
        "    OptionalField[field.name, field.type] for field in Fields[T]\n"
        ")\n"
        "```"
    ),
]
type ReadonlyField[Name, Type] = Annotated[
    Type,
    Doc(
        "Emits a required, read-only field into a `Record`. It uses "
        "the same output name and type arguments as `Field`, but the generated "
        "`TypedDict` value is wrapped in `ReadOnly`.\n\n"
        "```python\n"
        "type Frozen[T] = Record(\n"
        "    ReadonlyField[field.name, field.type] for field in Fields[T]\n"
        ")\n"
        "```"
    ),
]
type Drop = Annotated[
    Never,
    Doc(
        "Removes the current field from a `Record` result. `Drop` is commonly "
        "returned conditionally from a predicate branch; using it as the entire "
        "transform drops every field.\n"
        "\n"
        "```python\n"
        "@type_function\n"
        "def Public[T]():\n"
        "    return Record(\n"
        '        Map[field.name, Literal["password"]: Drop, ...: field]\n'
        "        for field in Fields[T]\n"
        "    )\n"
        "```"
    ),
]
