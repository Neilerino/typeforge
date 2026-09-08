# Typeforge

Typeforge describes authored type relationships and projects their meaning into
standard Python typing interfaces.

Use this reference when changing Map authoring, selection, or consumer support.
For module ownership, read [DESIGN.md](DESIGN.md); for runnable authoring examples,
read [README.md](README.md#examples).

## Language

**Runtime Input**:
The input whose type becomes available when a value is supplied for validation.
It is distinct from an unresolved static type parameter.

**Type symbol**:
The identity of an authored type parameter within its declaring scope. Two uses
of that parameter share a symbol; equally named parameters in different scopes
do not.

**Unresolved static type**:
A type whose concrete identity still depends on a type symbol, including a
parameterized type with unresolved positions. Known positions retain their meaning.

**Indeterminate result**:
A result whose selection cannot yet be decided from the available static type
information. Its possible alternatives are distinct from a definite union type.

**Possible output type**:
The type encompassing the outputs that a Map may produce. A no-match path
contributes no output type.

**Deferred Map**:
An ordered Map whose case selection awaits Runtime Input. Its cases, default,
and available bindings remain meaningful while selection is deferred.

## Map authoring

Use `Map` for conditional mapping and `Equal` for equality predicates.

```python
from typeforge import Assignable, Map

type Encoded[T] = Map[T, int: str, Assignable[bytes]: str, ...: T]
```

- **Branches:** supply a subject and at least one ordered branch. First match wins;
  the optional `...: output` fallback counts as a branch and must be last.
  Public authoring accepts slices; Case/Default are private normalized data.
- **Selectors:** concrete selectors match exactly; structural selectors such as
  `list[Value]` capture types. `Equal[list[Value]]` requires an existing Value
  binding. Callable overloads have the [limits below](#callable-support).
- **Scope:** unary Equal/Assignable binds the whole enclosing Map subject, through
  aliases and All/Any/Not. Binary operands remain explicit. Nested Maps establish
  their own subjects; outputs receive no implicit binding. Key/Value retain
  their field and capture roles.
- **Endpoints:** None and empty endpoints denote the None type. `int:` equals
  `int: None`; `:str` equals `None: str`; `:` is a None-to-None branch. An explicit
  None step is inert; other slice steps are invalid.
- **Literals:** strings and unary string predicate targets require
  `Literal["text"]`. Bytes, bool, and signed integers have selector shorthand;
  True and 1 remain distinct. Subjects and outputs use ordinary type expressions.
  Use `...:` for fallback; `typing.Any` retains type semantics.

For authoring changes, use the [cutover contracts](tests/unit/test_slice_cutover.py)
to check public rejection rules and executable documentation.

## Selection and validation

**No-match** is distinct from selecting Never. With no fallback, compiler Schema
selection uses Never; Pydantic rejects a reached no-match even inside an outer
union. **Indeterminate selection** retains reachable alternatives and provenance.
Predicate failures remain errors, subject to existing short-circuit rules.

**Runtime Input** selects against raw values before output coercion. Validation
failure ends that selection; it does not retry later branches. Pydantic owns
output validation, union ambiguity, metadata, serialization, and model rebuilds.
Map describes types rather than transforming values. Parameterized Input patterns
remain unsupported; dispatch does not infer generics from container contents.

## Normalization and integration

Source and runtime normalize separately because they receive different data.
Runtime normalization must precede Python's generic parameter discovery and
substitution; source normalization preserves authored locations without execution.
Alias-dependent binding stays with frontend expansion. For ownership or traversal
changes, read [unified type mapping](DESIGN.md#unified-type-mapping) and compare
[source regressions](tests/unit/compiler/source/test_slice_compiler_integration.py)
with [runtime regressions](tests/unit/pydantic/test_slice_normalization.py).

### Tooling and diagnostics

Raw slices require Typeforge projection for mypy, Pyright, and Pyrefly. For
formatter, linter, or checker changes, use the
[toolchain probes](tests/unit/test_slice_tooling.py): formatting must preserve the
AST, projection must pass checking, and incorrect returns must fail. Bare string
selectors need positive tooling evidence without suppressions before adoption.

Compiler diagnostics retain authored expressions and UTF-8 spans. Runtime
messages reconstruct slice notation while preserving codes, phases, inputs, and
field locations. They cannot recover whitespace, import aliases, or distinguish
empty endpoints from explicit None; bound unary predicates may display both
operands. For display changes, use
[diagnostic regressions](tests/unit/test_slice_diagnostics.py) to check
that alias bodies stay unevaluated and Literal/Annotated payloads stay opaque.

### Callable support

Schema selection and callable specialization have separate policies. Published
stubs use standard typing; relationship aliases publish as object, while overlays
use possible-output bounds for aliases and inline Maps. Callable relationships
require a generic controller; relationship aliases require one type parameter.

Each/Collect precision stops at the configured arity. Calls outside specialized
overloads retain aggregate bounds even when the authored Map has no fallback.
Unbounded structural outputs can fail emission. Overload subtype matching cannot
exclude bool from int; predicate candidate discovery and Assignable/isinstance
verification also have precision limits.

For specialization changes, use [publication regressions](tests/unit/compiler/pipeline/test_slice_publication.py)
to check finite arities, deterministic stubs, and all three checkers. Changes to
callable selection belong to the [separate proposal](docs/ideas/callable-map-semantics-cutover.md);
passing checker tests alone does not establish Schema-equivalent selection.

### Field support

TypedDict transforms support dropping, renaming, scalar Value mapping, union
outputs, and unchanged union fields. Compiler materialization uses named generic
record aliases; runtime Schema also supports the exercised inline form.

Field makes outputs required/writable, OptionalField optional/writable, and
ReadonlyField required/readonly: each replaces source flags. Compiler output uses
Annotated fields' base types; Pydantic retains constraints and schema metadata.
Duplicate names, non-field outputs, and speculative field-versus-Drop layouts
remain errors.

For record changes, use [field regressions](tests/unit/test_slice_fields.py) and
G5/G6 below. Inherited-record callable dispatch has an additional limit:
base-first overload ordering can hide a derived-record overload.

## Union support and open decisions

Normalization parity is established; selection equivalence depends on the
consumer. Before changing union behavior, use the
[union matrix](tests/unit/test_slice_union_matrix.py) to identify affected subject,
selector, output, alias, capture, Input, and callable cases. It retains U01–U31
and consumer probes. Agree on changed semantics before replacing a limitation
assertion with a passing regression.

### G1 — Union selectors

Shared evaluation distributes bare selectors over known subject members; unary
predicates compare the whole subject. Bare union selectors are exact union types
in static Schema evaluation, leaf alternatives for Input, and subtype-matched
overload parameters for callables. Cross-consumer meaning remains unsettled.

### G2 — Union equality

Resolved compiler equality depends on member order, unlike runtime equality.
Reconcile comparison with runtime and unresolved provenance while preserving
emitted order independently. U08/U30 are the witnesses.

### G3 — Union aliases

Compiler Schema expands ordinary union aliases; static runtime matching retains
alias identity. Input unwraps aliases; output validation delegates them to
Pydantic. Transparent runtime selection needs identity, metadata, and cycle rules.
U16/U18/U29 remain divergent.

### G4 — Any unions

Runtime semantic union construction absorbs Any; the compiler retains other
member paths. U24/U25 show why permissive schemas do not prove selection parity.
Portable selection involving Any-containing unions is not guaranteed.

### G5 — Field distribution

Compiler record discovery stores field annotations as opaque NamedType values.
The nested Value Map witness emits float for an int-or-str field, while Pydantic
distributes to bytes-or-float. Field discovery and downstream matching need a
separate change.

### G6 — Unsupported structures

Record-union operands and unions of structural capture patterns remain rejected.
Their support needs a separate design. Ordinary classes and parameterized dicts
remain outside the supported record families.
