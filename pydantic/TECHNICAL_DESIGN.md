# Typeforge Pydantic Integration

Status: Initial implementation complete; follow-ups remain
Audience: Typeforge maintainers and contributors  
Scope: Pydantic v2 integration

## Summary

The Pydantic integration gives Typeforge type expressions runtime meaning. A
user wraps an expression in `Schema[...]`; Typeforge interprets that expression
while Pydantic builds its core schema and returns validation and serialization
logic that Pydantic can compile.

```python
from typing import Literal, TypedDict

from pydantic import BaseModel
from typeforge import Drop, Equal, Field, If, Key, MapFields, Value
from typeforge.pydantic import Schema


class User(TypedDict):
    name: str
    email: str
    password: str


type Public[T] = MapFields[
    T,
    If[
        Equal[Key, Literal["password"]],
        Drop,
        Field[Key, Value],
    ],
]


class Request(BaseModel):
    user: Schema[Public[User]]
```

For this example, the static compiler exposes `Request.user` as the generated
`Public_User` `TypedDict`. At runtime, the Pydantic integration produces the
equivalent typed-dictionary core schema. Successful validation returns an
ordinary dictionary; `Schema` is not a value wrapper.

The integration supports two kinds of evaluation:

1. Schema-time evaluation resolves expressions whose inputs are already known.
   This adds no Typeforge-specific Python call to individual validations.
2. Value-time evaluation permits expressions to inspect an incoming value.
   Typeforge should prefer native Pydantic core-schema constructs, but it may
   use callable discriminators or validators when they materially improve the
   authoring experience.

The public boundary name is `Schema`. Value-time execution uses the explicit
`Input` controller described below.

## Implementation status

The initial integration implements:

- the optional `typeforge.pydantic` package and `Schema[T]` boundary;
- schema-time `Equal`, `Assignable`, `All`, `Any`, `Not`, `If`, and `Map`;
- structural schema-time `Map` patterns with `Value` capture;
- `TypedDict` `MapFields`, including renaming, optional, readonly, and dropped
  fields;
- strict raw-input dispatch with `Input` for value-time `Map` and `If`;
- Pydantic validation, serialization, JSON Schema, stable synthesized record
  definitions, and `Doc` descriptions;
- static compiler and overlay erasure of `Schema`, including value-time output
  unions; and
- dependency isolation: base Typeforge does not import Pydantic.

Current follow-ups are intentionally explicit:

- recursive aliases containing Typeforge operators report a schema-generation
  error; ordinary recursive aliases are delegated to Pydantic;
- static record materialization currently requires a named generic
  `MapFields` alias, while runtime validation also accepts the inline form;
- value-time generic pattern capture and nested field access are not defined;
- validation-mode JSON Schema for value-time dispatch is deliberately `{}`
  until its raw input language can be represented faithfully;
- the shared source/runtime semantic protocol remains an architectural
  extraction rather than a completed package split; and
- plan explanation, benchmarks, wrap-validator fallback cases, and a
  `BaseModel` record adapter remain follow-up work.

## Goals

- Let Pydantic models and `TypeAdapter` consume Typeforge type expressions.
- Preserve one meaning for an expression across static compilation and runtime
  schema construction.
- Compile recognizable expressions to native `pydantic-core` schemas.
- Permit Python-backed runtime expressions when native schemas cannot express
  the desired behavior cleanly.
- Support Pydantic validation, serialization, and JSON Schema generation.
- Keep the core Typeforge marker layer dependency-free and inert.
- Preserve Pydantic metadata and behavior on ordinary leaf types by delegating
  their schema construction back to Pydantic.
- Make the selected execution strategy inspectable and testable.
- Represent expected integration failures with typed results internally, then
  raise a Pydantic-compatible exception at the extension boundary.

## Non-goals

- Reimplement Pydantic's type coercion or ordinary validation rules.
- Make Typeforge a general-purpose expression language for arbitrary Python
  business logic.
- Silently treat every annotated class as the same kind of record.
- Guarantee that every Typeforge callable relationship has useful model-field
  semantics. `Each` and `Collect`, for example, are initially out of scope.
- Mutate authored annotations or model classes after Pydantic has compiled them.
- Require Pydantic for users who only use Typeforge's static compiler.

## Terminology

- **Type expression**: A Typeforge expression such as `Map[...]`, `If[...]`, or
  `MapFields[...]`.
- **Schema boundary**: The outer `Schema[...]` annotation that opts an expression
  into Pydantic integration.
- **Schema-time evaluation**: Evaluation performed while Pydantic constructs a
  model or `TypeAdapter` schema.
- **Value-time evaluation**: Evaluation that depends on an incoming Python or
  JSON value and therefore runs during validation.
- **Execution plan**: A backend-neutral description of how an evaluated
  expression will be implemented.
- **Record adapter**: An explicit adapter for one record family, such as
  `TypedDict` or `BaseModel`.

## Public API

### `Schema`

The integration is imported explicitly:

```python
from typeforge.pydantic import Schema
```

It can be used in a model field or with `TypeAdapter`:

```python
from pydantic import BaseModel, TypeAdapter
from typeforge import Case, Default, Map
from typeforge.pydantic import Schema


type Wire[T] = Map[
    T,
    Case[bytes, str],
    Default[T],
]


class Envelope(BaseModel):
    value: Schema[Wire[bytes]]


wire_adapter = TypeAdapter(Schema[Wire[bytes]])
```

`Schema[T]` means: interpret `T` as a Typeforge expression, construct the
corresponding Pydantic core schema, and expose the expression's resolved output
type to static consumers.

The preferred implementation shape is an `Annotated` alias with private
metadata:

```python
type Schema[T] = Annotated[T, _SchemaMetadata()]
```

This gives ordinary type checkers the best available fallback while allowing
`_SchemaMetadata` to implement `__get_pydantic_core_schema__`. A prototype must
verify that supported Pydantic and Python versions preserve the parameterized
PEP 695 alias long enough for the metadata hook to inspect it. If Pydantic
expands the inner alias before the hook receives it, the fallback design is a
generic marker class whose hook reads `get_args(source_type)`.

### Value-time input

Value-time evaluation uses the explicit `Input` controller:

```python
from uuid import UUID

from typeforge import Case, Map
from typeforge.pydantic import Input, Schema


type Identifier = Schema[
    Map[
        Input,
        Case[int, int],
        Case[str, UUID],
    ]
]
```

This example intends to preserve integer inputs and parse string inputs as
UUIDs. Its output type is `int | UUID`.

`Input` observes the raw Python value before branch validation. Python and JSON
inputs use the Python type produced by `pydantic-core` at the dispatch boundary.
`Case[int, ...]` means `type(value) is int`, so `bool` does not match `int` and
case selection never performs coercion. Cases are ordered and the first exact
match wins; the selected output schema then applies normal Pydantic validation.
Generic value-time patterns and nested field access remain undefined and fail
rather than silently changing the static meanings of `Equal` or `Assignable`.

## Semantic model

The static compiler and Pydantic integration must not implement separate
meanings for Typeforge operators. They should share a semantic expression model
and evaluator.

The current compiler has related representations in `compiler/model.py`,
`compiler/lowering.py`, `compiler/records.py`, and `compiler/evaluator.py`.
Introducing the integration is an opportunity to separate three concerns:

1. Frontends parse source or runtime typing objects.
2. A shared evaluator resolves Typeforge relationships.
3. Backends emit stubs, overlays, or Pydantic schemas.

A possible package shape is:

```text
src/typeforge/
    semantics/
        model.py
        evaluation.py
        protocols.py
    pydantic/
        __init__.py
        annotation.py
        frontend.py
        planning.py
        emitter.py
        records.py
        errors.py
```

This layout is provisional. The important boundary is that Pydantic-specific
objects do not enter the shared semantic model.

### Type-system protocol

The evaluator needs operations whose implementation differs between source
analysis and runtime reflection. A generic protocol can provide them:

```python
class TypeSystem[T](Protocol):
    def equal(self, left: T, right: T) -> Result[bool, EvaluationError]: ...

    def assignable(self, source: T, target: T) -> Result[bool, EvaluationError]: ...

    def union(self, members: tuple[T, ...]) -> Result[T, EvaluationError]: ...

    def record(
        self,
        value: T,
    ) -> Result[RecordShape[T], RecordError]: ...
```

The exact protocol will evolve, but it should operate on immutable Typeforge
data and return typed failures. Source analysis can use checker-neutral type
references. Runtime evaluation can use handles to actual Python typing objects.

### Record shapes

Record data remains explicit and family-aware:

```python
@dataclass(frozen=True, slots=True)
class RecordShape[T]:
    family: RecordFamily
    name: str | None
    fields: tuple[RecordField[T], ...]


@dataclass(frozen=True, slots=True)
class RecordField[T]:
    name: str
    value: T
    required: bool
    readonly: bool
```

`RecordFamily` prevents a transformed `TypedDict` from accidentally inheriting
Pydantic-model construction semantics, or vice versa.

## Runtime frontend

The runtime frontend receives the expression inside `Schema[...]` and converts
Python typing objects into the semantic expression model. It must understand:

- Typeforge's marker aliases by object identity, not only by their names;
- PEP 695 `TypeAliasType` objects;
- parameterized user aliases and type-parameter substitution;
- `Annotated`, including preservation of non-Typeforge metadata;
- unions, literals, generic applications, and forward references;
- nested and recursive aliases;
- Typeforge aliases re-exported from other modules.

For example, resolving `Public[User]` requires binding `T` to `User`, expanding
the alias value, and retaining `User` as a runtime type reference while parsing
the `MapFields` expression.

Runtime parsing must be cycle-aware. Recursive aliases should produce explicit
semantic references rather than recurse indefinitely. Those references later
become Pydantic definition references where supported.

The parser returns a typed error for malformed or unsupported expressions. It
must not fall back to the inert runtime value of a Typeforge marker, because
doing so could silently turn a validation schema into `object`.

## Evaluation and planning

Evaluation produces either a resolved type/record or a plan that still depends
on the incoming value. Planning then selects the least expensive faithful
Pydantic implementation.

The planner uses the following preference order:

1. **Resolved schema**: The expression is completely resolved at schema build.
2. **Native core schema**: The behavior maps directly to a Pydantic schema node.
3. **Callable discriminator**: Python selects a branch and `pydantic-core`
   validates the selected branch.
4. **Before, after, or plain validator**: A one-direction transformation fits a
   more specific validator kind.
5. **Wrap validator**: General fallback requiring access to both the input and
   nested validation.

This is an optimization hierarchy, not a prohibition. A wrap validator is a
valid implementation when it provides useful behavior that cannot be expressed
faithfully with a cheaper plan.

Possible immutable planning data includes:

```python
@dataclass(frozen=True, slots=True)
class ResolvedPlan[T]:
    output: T


@dataclass(frozen=True, slots=True)
class UnionPlan[T]:
    choices: tuple[T, ...]


@dataclass(frozen=True, slots=True)
class DispatchPlan[T]:
    cases: tuple[DispatchCase[T], ...]
    strategy: DispatchStrategy


type ValidationPlan[T] = ResolvedPlan[T] | UnionPlan[T] | DispatchPlan[T]
```

Planning data should not contain Pydantic core-schema dictionaries. That keeps
planning testable without Pydantic and lets future integrations consume the same
semantic result.

## Pydantic schema emission

The emitter translates a validation plan into `pydantic_core.CoreSchema`.

### Ordinary types

Ordinary leaf types are delegated to `handler.generate_schema(type)` rather
than reimplemented. This preserves Pydantic support for models, dataclasses,
constraints, custom types, recursive definitions, and other `Annotated`
metadata.

The integration should construct core schemas directly only for shapes that do
not already exist as a concrete Python type, such as a `MapFields` result.

### `If`

When its condition is schema-time resolvable, `If` emits only the selected
branch's schema.

When its condition depends on input, the planner may emit:

- a native union if normal Pydantic branch selection has the same semantics;
- a tagged union with a callable discriminator returning a boolean branch tag;
- a wrap validator for conditions that require validation state or a
  transformation before selection.

Both branch schemas should still be built by the handler or native emitter, so
only the decision logic runs in Python.

### `Map`

When its subject is concrete, `Map` evaluates its cases once and emits the
selected output schema.

For a value-time subject, cases remain ordered. The initial recommended runtime
semantics are strict, pre-coercion matching so that selecting a case does not
itself mutate the input. The selected output schema then performs normal
Pydantic validation and coercion. This recommendation remains open until the
`Input` design is accepted.

The implemented backend uses a Python before-validator to attach an internal
case tag, a native tagged union for branch validation, and an after-validator to
remove the internal envelope. Serialization classifies the validated output
separately, avoiding the ambiguity between a raw input type and another case's
output type. A wrap validator remains an accepted future fallback when a
condition cannot be represented faithfully with this plan.

The static output type of a value-time `Map` is the union of all reachable case
outputs and its default. An omitted default makes unmatched input a validation
error; it must not silently validate as `object`.

### Unions

Typeforge unions should preserve Pydantic's normal union behavior unless a
Typeforge expression promises ordered first-match behavior. Ordered `Map` cases
and Pydantic smart unions are not interchangeable.

If Typeforge can recognize a literal discriminator in record alternatives, it
may emit a tagged union directly. Otherwise it emits a normal or left-to-right
union according to the expression's declared semantics.

### `MapFields`

The first implementation supports `TypedDict` input records. It emits a native
typed-dictionary schema containing transformed fields:

- `Field` emits a required field;
- `OptionalField` emits `required=False`;
- `Drop` omits the field;
- `ReadonlyField` has the same validation behavior as a required field and
  carries static or serialization metadata where meaningful;
- renamed fields use their transformed names;
- transformed field values are recursively evaluated and emitted.

The output value is a dictionary. The schema should use a deterministic name or
reference derived from the alias and concrete input record so that JSON Schema
definitions are stable.

Pydantic `BaseModel` transformation is a separate record adapter. It must define
how field validators, model validators, serializers, computed fields, aliases,
defaults, private attributes, model configuration, and output class identity
behave. Until that adapter exists, `MapFields[SomeBaseModel, ...]` fails during
schema construction rather than pretending the model is a `TypedDict`.

### Unsupported callable relationships

`Each` and `Collect` describe relationships across callable arguments. Using
them directly inside a model field initially produces a typed schema-generation
error. A future `validate_call` integration can define their runtime meaning
separately.

## Serialization and JSON Schema

`Schema[...]` represents a complete Pydantic schema, not validation alone.

Resolved ordinary types inherit their serializer and JSON Schema behavior from
Pydantic. Synthesized record schemas use the same transformed shape for
validation and serialization unless an operator explicitly specifies otherwise.

`Doc` metadata should become a JSON Schema description on the resolved type or
field. Named aliases should produce deterministic `$defs` entries rather than
copying large schemas at every use site. Recursive expressions should use
definition references.

Value-time dispatch must also define serialization behavior. The preferred
strategy is to let each selected output schema serialize its validated output.
If output branches overlap such that a serializer cannot identify the branch,
schema construction should either require an explicit discriminator or report
an ambiguity.

Validation-mode and serialization-mode JSON schemas may differ when Python
validators accept a broader input than the output type. The integration should
provide input schema metadata when it can describe that input honestly. It must
not claim a narrower JSON input schema merely because the output is narrow.

## Static compiler integration

The source compiler treats `Schema[T]` as a transparent integration boundary
whose static type is the evaluated output of `T`.

For schema-time expressions, this is the same result used by the runtime
evaluator. For value-time expressions, the output is the union of all reachable
branches. Generated library stubs contain only standard typing constructs and
must not require Typeforge or Pydantic integration markers unless the public API
already requires Pydantic.

The overlay and stub emitter should remove `Schema[...]` after specializing the
inner expression. This prevents users from seeing a fictitious wrapper object
and keeps constructor, attribute, and return types aligned with actual runtime
values.

The compiler must verify that its output type agrees with the runtime plan. A
useful internal contract test is:

```text
source expression
    -> static semantic evaluation -> emitted standard type
    -> runtime semantic evaluation -> plan output type

assert normalized static type == normalized runtime output type
```

## Error handling

Internal APIs return typed errors. Suggested categories include:

- `RuntimeExpressionError`: malformed aliases, unresolved forward references,
  unsupported runtime typing objects, or recursive expansion failures;
- `EvaluationError`: invalid arity, unbound `Key`, `Value`, or runtime input,
  incompatible condition operands, and unreachable or duplicate cases;
- `RecordAdapterError`: unsupported record family or unsupported field feature;
- `PlanningError`: behavior cannot be represented by an enabled execution
  strategy;
- `SchemaEmissionError`: failure while delegating to or constructing a Pydantic
  core schema;
- `SerializationAmbiguityError`: output branches cannot be serialized
  consistently.

The `__get_pydantic_core_schema__` hook is an API boundary where exceptions are
expected. It converts a typed Typeforge error into a concise Pydantic-compatible
schema-generation exception. The message should include:

- the authored expression;
- the failing operator;
- whether failure occurred during parsing, evaluation, planning, or emission;
- a suggested correction when one is known.

Per-value predicate failures become ordinary Pydantic validation errors with
stable Typeforge error codes and useful locations.

## Caching and performance

Pydantic compiles a model's core schema when the model is built and compiles a
`TypeAdapter` when the adapter is instantiated. Typeforge should avoid adding
work after that point unless the expression is intentionally value-dependent.

Safe cache candidates include:

- parsed runtime aliases keyed by the parameterized alias object;
- normalized semantic expressions;
- schema-time evaluation results;
- immutable execution plans.

Core-schema dictionaries should not be cached globally across Pydantic handlers.
Handler context, definitions, configuration, and surrounding `Annotated`
metadata can affect emission. Pydantic remains responsible for caching compiled
validators and serializers.

Value-time plans should document their expected Python call count:

- resolved or native plan: zero Typeforge Python calls per validation;
- tagged input dispatch: two validation calls plus core validation;
- before/after/plain validator: normally one call;
- wrap validator: one or more calls depending on nested handler use.

`typeforge explain` should eventually expose this information:

```text
Schema: Identifier
Plan: tagged input dispatch
Cases: int -> int, str -> UUID
Typeforge Python calls per validation: 2
Branch validation: pydantic-core
Output: int | UUID
```

Performance tests must separate schema-build cost from steady-state validation
cost. Benchmarks should compare Typeforge schemas with equivalent hand-written
Pydantic types rather than asserting an absolute timing threshold.

## Dependency and compatibility policy

Pydantic is an optional dependency. Importing `typeforge` must not import
Pydantic or `pydantic-core`. Importing `typeforge.pydantic` without the optional
dependency should fail with a focused installation message.

The integration targets Pydantic v2. The supported minimum version should be
chosen after the initial alias-preservation and core-schema prototypes. CI
should test the minimum supported version and the newest compatible v2 release.

The integration uses public custom-schema hooks and core-schema constructors. It
must not depend on Pydantic's private `GenerateSchema` implementation. Because
the core-schema extension surface can evolve between releases, compatibility
code belongs behind a small Typeforge-owned emitter interface.

## Testing strategy

### Unit tests

- Runtime parsing of every Typeforge marker.
- PEP 695 generic alias expansion and substitution.
- Nested aliases, `Annotated` metadata, forward references, and recursion.
- Shared evaluator behavior for `Equal`, `Assignable`, `If`, and `Map`.
- Execution-plan selection independent of Pydantic.
- Typed error values for invalid and unsupported expressions.

### Static/runtime contract tests

- The compiler's resolved output matches the runtime plan's output.
- A `Schema[...]` wrapper disappears from generated stubs and overlays.
- Value-time branch unions are complete and contain no unreachable outputs.
- Record transforms agree on required, optional, readonly, renamed, and dropped
  fields.

### Pydantic integration tests

- `BaseModel` field validation from Python and JSON.
- Reusable `TypeAdapter` validation and serialization.
- Native, callable-discriminator, and wrap-validator plans.
- Pydantic leaf metadata such as constraints and custom types.
- Validation-error paths and stable Typeforge error codes.
- JSON Schema in validation and serialization modes.
- Recursive types and `$defs` reuse.
- Model rebuilds and forward-reference resolution.

### Performance tests

- Schema-build overhead for representative expressions.
- Steady-state native plan versus an equivalent hand-written annotation.
- Callable-discriminator overhead versus a hand-written discriminator.
- Wrap-validator overhead versus a hand-written wrap validator.
- Large `MapFields` schemas and repeated alias reuse.

## Delivery sequence

1. Prototype `Schema[...]` with PEP 695 aliases on the supported Python and
   Pydantic versions.
2. Extract or introduce the shared semantic expression model and evaluator.
3. Implement the runtime typing frontend for schema-time `If` and `Map`.
4. Emit ordinary resolved types through the Pydantic handler.
5. Add static compiler handling that erases `Schema[...]`.
6. Implement the `TypedDict` `MapFields` adapter.
7. Add JSON Schema naming, documentation, and recursive references.
8. Specify and implement the value-time controller and matching semantics.
9. Add callable-discriminator and wrap-validator planning.
10. Add explanation output and representative benchmarks.
11. Design `BaseModel` record transformation as a separate follow-up.

Each step should leave a usable vertical slice. Value-time execution should not
block shipping schema-time expression support.

## Open questions

1. Is `Schema[T]` implemented as an `Annotated` alias or a generic marker class?
2. Is `Input` the right public name for value-time input?
3. Does runtime case matching use exact type, `isinstance`, structural matching,
   or an explicit family of predicates?
4. How are raw JSON values represented to runtime predicates before Python-mode
   coercion?
5. Should callable-discriminator and wrap plans be automatic, explicitly opted
   into, or configurable per project?
6. How should users request strict versus coercive matching?
7. What is the fallback behavior for ambiguous or overlapping runtime cases?
8. Should `Schema` also be usable outside Pydantic as a general runtime-schema
   boundary in the future, or is it intentionally Pydantic-specific?
9. How should Pydantic `Field` metadata compose with field metadata produced by
   `MapFields`?
10. What is the exact runtime meaning of `ReadonlyField` during serialization
    and assignment validation?
11. Can recursive synthesized record schemas always receive stable references
    without relying on Pydantic internals?
12. What subset of `BaseModel` field and model behavior can a future record
    adapter preserve honestly?

## Decisions

### Accepted

- The public integration boundary is named `Schema`, not `Validated`.
- `Schema[...]` returns the resolved value; it does not construct a wrapper
  instance.
- Python-backed value-time evaluation is allowed when it provides useful
  expressiveness.
- The planner prefers cheaper native schemas when they preserve the same
  semantics.
- Record families require explicit adapters.
- Pydantic remains an optional dependency.

### Proposed

- Use `Input` as an explicit value-time controller.
- Prefer strict, pre-coercion matching for runtime `Map` cases.
- Prefer callable tagged-union discriminators over full wrap validators for
  branch selection.
- Support `TypedDict` record transforms before `BaseModel` transforms.
- Add execution-plan details to `typeforge explain`.

### Rejected

- `Validated` as the public boundary name, because it describes a state rather
  than the schema-construction operation.
- A blanket prohibition on wrap validators.
- Treating Pydantic models as typed dictionaries during `MapFields` evaluation.
- Silently accepting unresolved marker fallbacks such as `object`.
