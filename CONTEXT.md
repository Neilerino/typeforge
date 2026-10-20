# Typeforge

Typeforge describes authored type relationships and projects their meaning into
standard Python typing interfaces.

Use this reference when changing Map authoring, selection, or consumer support.
For module ownership, read [DESIGN.md](DESIGN.md); for runnable authoring examples,
read [README.md](README.md#examples).

For evolving selector semantics, minimize Typeforge-specific checking and retain
existing checkers as the owners of ordinary Python inference and expression
compatibility. See the [delegation discussion](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#proxy-delegation-and-verification-boundary)
before promising unresolved match-type verification beyond representable output
bounds and supported generated checks.
The agreed scope allows unresolved internal relationships with useful standard
projections and supported generated obligations. Document bound-only checking;
full Scala-style dependent verification is not promised.

The [initial API decisions](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md) are complete
as of 2026-09-30. Scalar and union matching, selection aliases, resolved generic
compatibility, basic type functions, named and alternative captures, and
Record/Fields construction are implemented. Later slices remain pending. Read the agreed
batches before changing selector APIs, field construction, type-function scope,
or callable input contracts. The support descriptions below describe current
implementation unless explicitly identified as an agreed future contract.

Before implementing captures, type functions, field edits, or callable projections,
read the [derisking findings](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/type-function-derisking.md). Bounded
prototype/checker witnesses pass. The [agreed runtime boundary](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#runtime-construction-and-compiler-support)
keeps compilation optional and distinguishes runtime template construction from
the compiler's supported source forms. Compatibility frontiers and full
compiler/proxy integration remain implementation gates; the prototype is not
production support.

Basic type_function construction executes once during import and retains original
parameter identity in an immutable TypeAliasType. Specialization and Pydantic
rebuilds use the template; Schema remains the runtime evaluation boundary.
When changing construction, compiler body forms, or specialization, read
[Reusable type functions](DESIGN.md#reusable-type-functions) and
[the production contracts](tests/unit/test_type_function_contract.py).
When changing capture identity, isolation, or output lookup, read
[Named type captures](DESIGN.md#named-type-captures) and
[their compiler/runtime contracts](tests/unit/test_named_capture_contract.py).
For compatible Sequence captures or heterogeneous tuple elements, also read
[the interface capture contracts](tests/unit/test_interface_capture_contract.py).
For overlapping or nested pattern unions, read
[the alternative capture contracts](tests/unit/test_alternative_capture_contract.py);
each matching environment instantiates a complete output before unioning.
For record construction, field scope, passthrough metadata, or generic rebuilds,
read [explicit record semantics](DESIGN.md#explicit-record-semantics) and
[the compiler/runtime contracts](tests/unit/test_record_fields_contract.py).
For local generic scope, alias cycles, or composed record operands, read
[the local alias contracts](tests/unit/test_local_alias_contract.py) and
[Reusable type functions](DESIGN.md#reusable-type-functions).

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

**Whole-subject predicate**:
A predicate that tests the complete Map subject, including a union as a whole,
rather than independently testing each union member.

**Union equivalence**:
The agreed comparison of unions as sets of member types: member order and
repetition do not distinguish them. Current compiler limitations are recorded
under G2 below.

**Ordinary type alias**:
A name bound to a type that expands to that type for selection under the agreed
contract. NewType results are distinct and are outside this transparency rule;
current alias-selection limitations are recorded under G3 below.

## Map authoring

Use `Map` for conditional mapping and `Is` for exact whole-type matching.

```python
from typeforge import Is, Map

type Encoded[T] = Map[T, int: str, Is[bytes]: str, ...: T]
```

- **Branches:** supply a subject and at least one ordered branch. First match wins;
  the optional `...: output` fallback counts as a branch and must be last.
  Public authoring accepts slices; Case/Default are private normalized data.
- **Selectors:** bare scalar selectors use assignment compatibility, including
  inheritance, bool/int, numeric widening, and Any. `Is[Type]` compares the whole
  subject exactly. Structural selectors bind declared Capture tokens such as
  `Item = Capture("Item")`. Callable overloads have the
  [limits below](#callable-support).
- **Scope:** Is binds the whole enclosing Map subject, through
  aliases and All/Any/Not. Binary operands remain explicit. Nested Maps establish
  their own subjects; outputs receive no implicit binding. Record comprehensions
  bind `field.name`, `field.type`, and the complete `field`. Nested Maps reuse an
  already bound capture token.
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
selection and Pydantic reject a reached no-match even inside an outer union or
type application. Speculative output bounds may include an uncovered path;
they do not prove that an input is accepted. **Indeterminate selection** retains
reachable alternatives and provenance.
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

The [agreed projection policy](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#d6--callable-precision)
uses a conservative possible-output union when standard typing cannot express
the precise relationship. Retain or improve precision wherever it is supported;
projection limits must not redefine Map selection. Implementation is pending.
For callable Maps without a default, known unsupported inputs fail under the
agreed future contract. Project the accepted input domain into standard parameter
types where possible. If coverage cannot be represented soundly, require a bound,
specialization, or fallback. Possible normal outputs alone do not prove input
acceptance. See the [final callable decisions](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#final-callable-decision-batch--agreed-2026-09-30)
for guard checking and the existing bound-only verification limits.
For Each/Collect, an aggregate possible-output tuple is acceptable when individual
argument types are unavailable. Preserve per-position mapping when enough type
information and a faithful representation are available; the configured arity
limit alone does not make argument types unknowable.

For specialization changes, use [publication regressions](tests/unit/compiler/pipeline/test_slice_publication.py)
to check finite arities, deterministic stubs, and all three checkers. Changes to
callable selection belong to the [separate proposal](docs/ideas/callable-map-semantics-cutover.md);
passing checker tests alone does not establish Schema-equivalent selection.

### Field support

TypedDict transforms support dropping, renaming, scalar field.type mapping, union
outputs, and unchanged union fields. Compiler materialization uses named generic
record aliases; runtime Schema also supports the exercised inline form.

Whole-field passthrough preserves source flags and backend-owned metadata.
`Field(name=..., type=..., required=True, readonly=False)` constructs new field
data. Name and type are mandatory keywords. `field.replace(...)` changes only
supplied properties; omission differs from an explicit None type or false flag.
Replacing the complete type removes its metadata; wrapping field.type keeps that
metadata at the nested position. A new Record clears whole-record metadata;
explicit outer Annotated metadata applies to the new result.
Compiler output uses Annotated fields' base types; Pydantic retains constraints.
Duplicate names, non-field outputs, and speculative field-versus-Drop layouts
remain errors.

For record changes, use [field regressions](tests/unit/test_slice_fields.py) and
G5/G6 below. Inherited-record callable dispatch has an additional limit:
base-first overload ordering can hide a derived-record overload.

## Union support and agreed future contracts

Normalization parity is established; selection equivalence depends on the
consumer. Before changing union behavior, use the
[union matrix](tests/unit/test_slice_union_matrix.py) to identify affected subject,
selector, output, alias, capture, Input, and callable cases. It retains U01–U31
and consumer probes. Agree on changed semantics before replacing a limitation
assertion with a passing regression.

### G1 — Union selectors

The [agreed mixed-selector design](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#agreed-mixed-bare-and-whole-type-selectors)
uses ordered selection per known union member, with Is comparing the original
whole subject. Earlier branches do not shrink that whole subject. Generic
parameters retain their original arguments; captures bind matched types.
Unresolved relationships can retain useful output bounds. The initial public
surface retains bare compatibility matching and exact Is, removes Assignable,
and defers compound predicates and binary comparisons. Scalar matching and
public removal of Equal/Assignable/All/Any/Not are implemented. Known union
selection and whole-subject Is agree in compiler Schema and runtime evaluation.
Callable input and output projection remain separate pending slices.

The latest [bare-selector decision](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#revisited-assignable-example--bare-subclass-matching-requested)
requires Animal to match a Dog subclass. This revises the earlier exact-only
default; Is retains exact whole-type comparison. After checker verification, the
user chose to follow checker compatibility for bool/int: bool matches bare int,
and the proposed primitive exception is withdrawn. All three installed checkers
also accept a custom int subclass. Any and generic compatibility rules are agreed;
resolved generic compatibility and list/tuple-to-Sequence captures are implemented.
Callable projection still needs its owning slices.

Fixed resolved selectors support list/set/dict invariance, Sequence/frozenset/tuple
covariance, and Mapping with invariant keys and covariant values. Lists and tuples
project to Sequence; dict projects to Mapping. Any retains gradual compatibility
in invariant positions. Unknown generic variance reports a diagnostic rather
than choosing a fallback. Exact identity remains usable for opaque generic types.
Partially known shapes retain existing structural proofs and possible-output
bounds; full unresolved variance reasoning remains with callable precision.
The [generic contract](tests/unit/test_generic_selection_contract.py) verifies
compiler/runtime results and direct variance assignments in all three checkers.

Shared evaluation distributes bare selectors over known subject members; unary
predicates compare the whole subject. Bare union selectors use compatibility
in static Schema evaluation, leaf alternatives for Input, and subtype-matched
overload parameters for callables. Cross-consumer implementation parity with the
agreed contracts still needs derisking.

### G2 — Union equality

Resolved compiler equality now uses set equivalence, as runtime equality does.
It ignores member order and duplicates recursively inside parameterized types.
Emitted order is preserved independently; unresolved provenance retains its
existing comparison rules. U08/U30 and the
[union contract](tests/unit/test_union_selection_contract.py) are the witnesses.

### G3 — Union aliases

Compiler Schema and runtime matching expand ordinary aliases for selection,
including nested generic arguments and exact Is targets. Runtime expansion uses
the existing alias binding and cycle boundary, preserving parameter identity.
Selected output aliases still delegate metadata and schema references to
Pydantic. Runtime recursive output aliases remain supported by Pydantic; aliases
requiring recursive Typeforge selection report alias_cycle. The compiler retains
its authored cycle diagnostic. NewType is not an ordinary alias; its detailed
compatibility rules remain deferred. U16/U18/U29 and the
[alias contract](tests/unit/test_alias_selection_contract.py) now agree.

### G4 — Any unions

Runtime and compiler union construction retain explicit members beside Any.
U24/U25 and nested exact-comparison probes prove selection parity independently
of permissive validation.
The [agreed rules](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#d4--any-unions)
preserve explicit members such as Any-or-str for later comparison. Bare selectors
now follow checker compatibility for Any: Any matches int and int matches Any.
This supersedes earlier exact-only default matching; Is retains exact comparison.
Scalar compatibility, public removal, and explicit union preservation are
implemented. The public removal was approved in the
[second decision batch](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#second-decision-batch--agreed).
This does not require every downstream checker to display the same union
spelling; callable input/output precision remains a separate pending contract.

### G5 — Field distribution

Compiler record discovery stores field annotations as opaque NamedType values.
The nested field.type Map witness emits float for an int-or-str field, while Pydantic
distributes to bytes-or-float. The
[agreed correction](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#d5--union-valued-fields)
requires bytes-or-float in both consumers, preserving ordinary memberwise Map
selection inside fields. Field discovery and downstream matching still need
implementation changes.

### G6 — Unsupported structures

Record-union operands remain rejected. Structural capture alternatives evaluate
complete outputs in independent binding contexts; their production contract is
linked above.
The [agreed record-union design](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#agreed-record-union-support)
transforms each TypedDict alternative independently and preserves a union of
complete output shapes, including field correlations. The
[agreed capture-pattern design](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#agreed-unambiguous-capture-pattern-union)
supports alternative patterns such as list[Item]-or-set[Item] when captures are
unambiguous. The
[agreed overlapping-capture rule](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#agreed-conflicting-captures-across-alternatives)
evaluates each successful alternative with its own bindings and unions complete
outputs, preserving correlations. A matched alternative whose output requires an
unbound capture is an error. Initially, report it when evaluation needs that
binding, without a mandatory separate definition-time analysis pass. This capture
behavior is implemented; record-union support remains pending.
Ordinary classes and parameterized dicts remain outside the supported record families.

The [agreed field syntax](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#preferred-field-authoring--record-comprehensions)
uses Record/Fields comprehensions inside a type_function, with a locally bound
field exposing its name and type. Record/Fields construction, scoped references,
whole-field preservation, and Drop are implemented. The public cutover removes
MapFields and ambient Key/Value without compatibility shims. Field construction
and immutable replacement arrive next; union-valued transforms and correlated
record unions retain their own slices. Initial output is TypedDict; explicit
record-family adapters preserve room for future generated Protocols.

The [agreed no-match rule](https://github.com/Neilerino/typeforge/blob/neil/typeforge-api-review-artifacts/docs/ideas/map-selection-decisions.md#agreed-partial-static-no-match-failure)
fails a Map when a known subject member has no matching branch. Ordinary Never
union semantics remain those of Python. This decision supersedes earlier
Never-only outcomes for known unmatched inputs. Compiler Schema, record
materialization, and runtime evaluation now share this failure rule. Callable
input-contract projection remains pending; an output bound alone is not an
accepted-input contract.
