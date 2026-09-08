# Typeforge Pydantic integration

This document describes the implemented runtime integration and where to change
it. Public syntax and cross-consumer limitations live in
[CONTEXT.md](../CONTEXT.md); shared architecture and result boundaries live in
[DESIGN.md](../DESIGN.md#pydantic-runtime-integration).

## Public boundary

`typeforge.pydantic.Schema[T]` asks Pydantic to validate the evaluated output of
a Typeforge expression. It returns the ordinary validated value; there is no
Schema wrapper instance. Both model fields and `TypeAdapter` use the same hook.

```python
from typing import Literal, TypedDict

from pydantic import BaseModel
from typeforge import Drop, Field, Key, Map, MapFields, Value
from typeforge.pydantic import Schema


class User(TypedDict):
    name: str
    password: str


type Public[T] = MapFields[
    T,
    Map[Key, Literal["password"]: Drop, ...: Field[Key, Value]],
]


class Request(BaseModel):
    user: Schema[Public[User]]


request = Request(user={"name": "Ada", "password": "secret"})
assert request.user == {"name": "Ada"}
```

`Schema` is an `Annotated` alias with stateless metadata. The metadata hook
compiles the source supplied by Pydantic on each build, specialization, or
rebuild. Pydantic owns generic model lifecycle, leaf validation, constraints,
serializers, and compiled-schema reuse. Typeforge does not infer static generic
arguments from incoming values or cache CoreSchema dictionaries globally.

## Implementation ownership

All runtime modules below are in
[src/typeforge/pydantic](../src/typeforge/pydantic).

| Module | Responsibility |
| --- | --- |
| [`_annotation.py`](../src/typeforge/pydantic/_annotation.py) | Public Schema alias, hook, and presentation of typed failures as Pydantic exceptions. |
| [`_compile.py`](../src/typeforge/pydantic/_compile.py) | Adapt, evaluate, translate outcomes, emit, and recover permitted generic fallback failures. |
| [`_frontend.py`](../src/typeforge/pydantic/_frontend.py) | Recognize canonical markers, bind aliases and type parameters, preserve metadata and authored origins. |
| [`_type_system.py`](../src/typeforge/pydantic/_type_system.py) | Runtime type operations for shared evaluation, including generic substitutions. |
| [`_records.py`](../src/typeforge/pydantic/_records.py) | Reflect TypedDict fields and modifiers into shared record data. |
| [`_policy.py`](../src/typeforge/pydantic/_policy.py) | No-match acceptance, generic fallback precedence, and admissible Input tests. |
| [`_evaluation.py`](../src/typeforge/pydantic/_evaluation.py) | Translate semantic outcomes into runtime schema outputs or authored integration issues. |
| [`_emission.py`](../src/typeforge/pydantic/_emission.py) | Delegate resolved types, emit synthesized records, and build rejecting generic fallback schemas. |
| [`_deferred.py`](../src/typeforge/pydantic/_deferred.py) | Carry shared deferred plans in runtime annotations and emit dispatch, validation, and serialization schemas. |
| [`_observation.py`](../src/typeforge/pydantic/_observation.py) | Observe raw values and classify supported runtime tests without owning Map ordering. |
| [`_errors.py`](../src/typeforge/pydantic/_errors.py), [`_display.py`](../src/typeforge/pydantic/_display.py) | Structured issues and slice-based diagnostic display. |
| [`_markers.py`](../src/typeforge/pydantic/_markers.py) | Inert Input marker, independent of schema compilation. |

[`semantics`](../src/typeforge/semantics) owns expression traversal, ordered Map
selection, predicate short-circuiting, captures, field transformations, and
deferred selection. The integration composes its evaluator with a runtime
TypeSystem, Pydantic policy, and deferred-type adapter. There is no second
Pydantic expression evaluator or separate hierarchy of planner strategies.

## Schema construction

The public Map constructor has already normalized slice branches into private
Map/Case/Default aliases before the runtime frontend receives them. Recognition
uses marker identity. The frontend expands Typeforge aliases, applies bindings,
and retains origins for diagnostics. Unary selector predicates bind to the
enclosing Map subject, including through predicate aliases and compounds.
Nested Maps establish their own subject.

Ordinary recursive aliases are delegated to Pydantic. Recursive aliases
containing Typeforge operators fail with `alias_cycle`; they do not produce
recursive synthesized records. Unresolved annotation names retain Pydantic's
rebuild behavior.

For a resolved expression, shared evaluation produces a runtime type or record
shape. Emission continues the current Pydantic handler for the root annotation
so surrounding middleware survives. Nested fields and deferred outputs use
`handler.generate_schema`. Schema-time transformations add no Typeforge
validation callbacks; output types may still have their own Pydantic validators.

Unparameterized generics use defaults, then constraints, then bounds, then Any.
The frontend preserves generic provenance separately from the resulting runtime
type. A no-match or unsupported-record failure caused by permitted generic
fallback can produce a rejecting field schema, allowing the generic model to
exist and a concrete specialization to rebuild successfully. This recovery does
not hide unrelated concrete failures.

A reached no-match is rejected by Pydantic policy. Speculative no-match paths
contribute no possible output and are accepted during exploration. Explicitly
selecting Never is a separate emission error because Never has no values.

## Deferred Input selection

`Input` makes selection depend on the raw value supplied for validation:

```python
from uuid import UUID

from pydantic import TypeAdapter
from typeforge import Map
from typeforge.pydantic import Input, Schema

type Identifier = Schema[Map[Input, int: int, str: UUID]]

adapter = TypeAdapter(Identifier)
text = "550e8400-e29b-41d4-a716-446655440000"
assert adapter.validate_python(text) == UUID(text)
assert adapter.validate_python(42) == 42
```

Selection precedes coercion. Exact `int` excludes bool; Assignable predicates can
accept subclasses. Literals compare both type and value. Input union selectors
offer alternatives, and predicate compounds retain shared short-circuit rules.
JSON validation observes decoded values before output validation. Parameterized
runtime patterns such as `list[int]` and `list[Value]` are rejected; dispatch
does not inspect container contents to infer generic arguments.

The shared DeferredMap retains branch order and field/capture context.
`DeferredAnnotations` carries that plan through ordinary type construction,
metadata, and transformed fields, preparing its output schemas at build time.
At validation, a callable discriminator resumes shared selection using
`RawInput`. A native tagged union validates exactly the selected output.
Output validation failure cannot retry a later case or the default.

A wrap validator removes the private branch index from Pydantic error locations.
No-match and reached predicate failures use `typeforge_*` validation codes and
preserve the original input. Unexpected validator exceptions propagate.

Serialization classifies the validated output by output type; it does not rerun
raw-input selection. The first matching output classifier wins, with index zero
as the fallback when none matches. There is no retained branch history or
schema-build rejection for ambiguous serializers. Outputs with indistinguishable
runtime types therefore cannot reliably retain different branch serializers.

Deferred dispatch currently exposes `{}` in both validation-mode and
serialization-mode JSON Schema. It does not publish a precise accepted-input
schema or an output union, even though runtime serializers delegate to the
selected output schema.

## Records and metadata

TypedDict is the supported MapFields record family. Reflection handles generic
bindings, inheritance, requiredness, readonly flags, and Annotated metadata.
Shared field operators replace source flags: Field is required/writable,
OptionalField is optional/writable, and ReadonlyField is required/readonly.
Drop removes a field, and renamed outputs validate under the new name.

Emission produces a native typed-dictionary schema returning a dictionary,
ignoring extra inputs. Readonly fields add JSON Schema `readOnly` metadata;
they do not make the resulting dictionary immutable. Nested values delegate to
Pydantic, preserving constraints and serializers. Doc metadata supplies JSON
Schema descriptions. Pydantic's alias machinery owns definition references and
build-local reuse, including repeated synthesized record aliases.

Ordinary BaseModel and dataclass leaves retain Pydantic behavior, but they are
not MapFields record operands. Record unions and unions of structural capture
patterns remain unsupported. Each/Collect callable relationships have no
model-field validation meaning.

## Compiler boundary

The compiler's [semantic adapter](../src/typeforge/compiler/semantic_adapter)
lowers source expressions to the shared evaluator without importing or executing
application code. It treats Schema as a boundary whose emitted type is its
evaluated output; deferred Input uses a possible-output bound.

Sharing evaluation does not establish identical selection in every consumer.
Source and runtime type adapters differ on union ordering, alias identity, Any
unions, and field discovery. Callable overload specialization has its own
limits. Before extending those cases, consult
[G1–G6](../CONTEXT.md#union-support-and-open-decisions) and the
[union matrix](../tests/unit/test_slice_union_matrix.py). These differences need
explicit decisions and derisking before their limitation tests change.

Neither compiler implementation nor runtime integration imports the other.
Static integration diagnostics and compiler plugin loading remain separate work.

## Failures and dependency isolation

Internal integration boundaries return typed SchemaIssue failures, including
MapNoMatchIssue, UnsupportedRecordIssue, and UnresolvedAnnotationIssue. Shared
SemanticIssue and MapNoMatch outcomes are translated once using frontend origins.
Private helpers may raise modeled exceptions inside a declared result boundary;
unexpected failures propagate.

The Schema hook raises PydanticUndefinedAnnotation for unresolved names and
PydanticSchemaGenerationError for other schema issues. Diagnostic display
reconstructs slice notation without expanding alias bodies or interpreting
Literal and Annotated payloads. Codes, phases, and authored locations remain
independent of display formatting.

Pydantic is optional. Base Typeforge imports do not load it; the integration's
import guard supplies an installation message only for missing Pydantic or
pydantic-core modules. Supported versions are declared in
[pyproject.toml](../pyproject.toml). The
[CI workflow](../.github/workflows/tests.yml) installs the locked environment
with all extras and runs `make check`; it does not currently test minimum and
latest dependency versions separately.

## Verification and follow-up work

Run `make check` for repository validation. For runtime changes, start with
`make check src/typeforge/pydantic tests/unit/pydantic`.

Use these contracts when changing a responsibility:

- [Runtime pipeline](../tests/unit/pydantic/test_runtime_pipeline.py): no-match,
  generic fallback, callback-free resolved emission, and unexpected failures.
- [Aliases and structures](../tests/unit/pydantic/test_aliases_and_structures.py):
  binding, captures, cycles, metadata, and rebuild isolation.
- [Deferred pipeline](../tests/unit/pydantic/test_deferred_pipeline.py): raw
  selection, short-circuiting, output failure, error paths, and serialization.
- [MapFields](../tests/unit/pydantic/test_map_fields.py) and
  [JSON Schema](../tests/unit/pydantic/test_json_schema.py): transformed records,
  metadata, definition reuse, and ordinary recursive aliases.
- [Slice integration](../tests/unit/pydantic/test_slice_integration.py) and
  [diagnostics](../tests/unit/test_slice_diagnostics.py): public spelling and
  authored error presentation.

Follow-up designs remain necessary for BaseModel record transforms, recursive
Typeforge aliases, callable validation, precise deferred JSON Schema, and
serialization that distinguishes overlapping outputs. A BaseModel adapter must
specify validator, serializer, default, alias, configuration, and class-identity
behavior before treating models as transformable records.

A minimum/latest Pydantic compatibility matrix, explanation output, and
schema-build versus steady-state benchmarks are also future work. These are
not implemented planner features or prerequisites for unrelated feature work.
