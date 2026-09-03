# Deferred Map Semantics and Compiler Cutover

Status: In progress
Depends on: Parameterized type pattern semantics
Related design: `docs/ideas/pydantic-integration-redesign.md`

## History

The original deferred `Input` slice is complete: shared semantics can represent
`Map[Input, ...]` as `DeferredMap` and calculate its possible output type.
Compiler adapters for parameterized types, structural case roles, and `Input`
lowering are also complete.

An attempted pipeline cutover exposed additional behavior that the shared model
does not yet represent completely. The experiment is preserved in commit
`49356b9` and reverted by `dfc49f4`. Use that commit as a failure inventory, not
as an implementation template: it combined the cutover with too many semantic
changes to review safely.

This task is reopened to finish the semantic prerequisites in reviewable slices
before attempting the compiler cutover again.

## Current state

### Complete

- Shared semantics owns recursive parameterized-type matching.
- Structural patterns preserve repeated `Value` capture consistency.
- Parameterized output templates rebuild backend types through `TypeSystem`.
- An unbound `InputReference` in `Map` subject position produces `DeferredMap`.
- `DeferredMap.possible_output` is normalized through `TypeSystem.union()`.
- Compiler `StaticType` includes `ParameterizedType`.
- `CompilerTypeSystem.inspect()` and `build()` round-trip parameterized types.
- Compiler semantic lowering distinguishes concrete parameterized types,
  parameterized patterns, parameterized templates, and `InputReference`.
- The five compiler adapter and semantic-lowering contracts in
  `tests/unit/compiler/test_type_system.py` and
  `tests/unit/compiler/test_semantic_lowering.py` pass without xfails.

### Not cut over

Schema-boundary resolution still runs through compiler lowering IR in
`src/typeforge/compiler/_pipeline_adaptation.py`. That path still owns:

- recursive `resolve_schema_type()` traversal across applications, unions, tuples,
  field transforms, and nested schema boundaries;
- `_resolve_schema_map_member()` and first-match case selection;
- `_match_schema_pattern()` and `_substitute_schema_capture()`;
- `resolve_schema_predicate()`, `_schema_assignable()`, and unresolved-variable
  detection;
- `union_types_for_schema()` normalization;
- direct output-union calculation for `RuntimeInputType`.

The duplicate path remains intentionally until the prerequisites below are
complete and the production pipeline can move in one small change.

## Existing deferred `Input` contract

Given:

```python
Map[
    Input,
    Case[int, int],
    Case[str, UUID],
    Default[bytes],
]
```

`evaluate()` returns a `DeferredMap` preserving:

- authored case order;
- each case test and output;
- the optional default;
- the current `EvaluationContext`;
- `int | UUID | bytes` as its possible output type.

Without a default, no-match remains a failure and contributes no output type.
An unbound `Input` outside a supported deferred `Map` remains
`UnboundInputSemanticError`.

`DeferredMap` contains semantic data only. Raw values, validators, serializers,
`CoreSchema`, JSON Schema, and Pydantic strategy remain integration concerns.

## Design gaps exposed by the cutover experiment

### Output templates must compose through unions

Captured `Value` can occur across union and parameterized-type boundaries:

```python
Case[list[Value], set[Value] | None]
Case[list[Value], tuple[Value | None]]
```

The output role must survive every nested position. Falling back to concrete
type lowering turns `Value` into an opaque named type and emits invalid output
such as `tuple[Value | None]`.

### String literals have contextual roles

`Literal["name"]` is a `FieldName` in a `MapFields` name expression, but it is a
normal typing type in schema output:

```python
Field[Literal["renamed"], Value]
Case[int, Literal["accepted"]]
```

Lowering must receive an explicit role. A global string-Literal special case is
not sufficient.

### Possible output types must compose

A possible output may itself be deferred:

```python
Map[
    Input,
    Case[int, Map[Input, Case[int, str], Default[float]]],
    Default[bytes],
]
```

The outer possible output is `str | float | bytes`. Aggregation must accept both
`ResolvedType` and `DeferredMap.possible_output`; it must not reject a nested
`DeferredMap` as a non-type and must not recalculate its cases in the compiler.

### Unresolved static types are not runtime `Input`

A generic parameter at schema generation time has unresolved type identity:

```python
class Payload[T]:
    value: Schema[
        Map[T, Case[Equal[T, int], str], Default[bytes]]
    ]
```

This is different from authored runtime `Input`. Rewriting `T` to `Input`
over-unions every case and loses first-match ordering. Shared semantics needs an
explicit representation for unresolved static type identity.

Conditions and patterns over unresolved types need three outcomes:

- match or true;
- mismatch or false;
- indeterminate.

Indeterminate case selection must preserve ordering. At the first indeterminate
case, the possible result is the selected output plus the recursively reachable
remainder. Earlier definite matches still short-circuit and definite failures
still fall through.

Uncertainty must preserve symbolic identity and structure:

- `T` compared with `T` is definitely equal;
- `list[T]` matches `list[T]`;
- `T` compared with `int` is indeterminate;
- `tuple[int, T]` cannot match `tuple[str, int]` because a known argument
  already differs;
- repeated `Value` captures become indeterminate only when equality depends on
  an unresolved position;
- nested indeterminate Maps must retain uncertainty when used by a predicate.

### Schema aliases must retain source meaning

Callable `Map` lowering and schema `Map` evaluation are separate lanes:

```text
callable annotation -> compiler MapType IR -> overload lowering
schema annotation   -> shared semantic expression -> evaluation -> emitted type
```

Compiler `MapType` is unsuitable as shared semantic input because adaptation has
already assigned callable roles and converts an omitted default into explicit
`Never`. Schema aliases therefore need their authored semantic source until
shared lowering occurs.

Alias expansion must:

- bind generic alias parameters before structural `Value` capture;
- support nested aliases;
- detect cycles explicitly;
- preserve omitted default versus `Default[Never]`;
- carry alias context through an honest interface rather than an optional
  parameter that silently produces incomplete output.

### Compiler adaptation has cross-cutting requirements

The cutover implementation must provide these outcomes without prescribing the
helper or module shapes in advance:

- newly added source-expression variants are handled exhaustively by alias
  expansion and substitution;
- `StaticType` has one conversion policy for emitted `TypeExpression`, including
  context-sensitive `Never` spelling;
- expected `SemanticLoweringError | SemanticIssue` failures are converted once
  at a deliberate compiler result boundary.

Choose concrete helpers only when the implementation identifies two real
callers. Keep them private supporting adapters rather than new compiler concepts.

## Implementation sequence

Each slice should be independently reviewable and leave `make check` green.
Work test-first from the named interface; avoid combining later slices into the
current one.

### 1. Characterize the production compiler behavior

Add focused `generate_module()` contracts for compiler behavior discovered
during the experiment. Cover:

- direct and aliased structural Maps;
- `Literal` as a field name and as a type output;
- top-level and nested union output templates containing `Value`;
- union subjects and nested union normalization inside structural types;
- Maps nested beneath applications, unions, starred types, and nested `Schema`;
- nested deferred `Input` Maps;
- duplicate possible outputs, omitted defaults, and explicit `Default[Never]`;
- unresolved generic predicates with earlier known true, known false, and exact
  cases;
- unresolved exact and structural cases;
- same-symbol identity and known mismatches in partially unresolved structures;
- repeated captures involving unresolved positions;
- nested uncertain Maps used by predicates;
- nested aliases and alias cycles.

Classify every row as either retained behavior or an intended correction:

- retained behavior becomes a green `generate_module()` characterization test;
- intended corrections are recorded in the matrix without asserting the known
  wrong output;
- before implementing a correcting slice, add its strict failing contract at
  that slice's owning interface (`evaluate()`, compiler semantic lowering, or
  schema adaptation), then remove the xfail in that same slice;
- add or activate end-to-end `generate_module()` correction coverage only when
  production boundaries cut over in slice 8.

Do not change production code in this slice.

Completion criterion: every surfaced case is classified, all retained-behavior
characterization tests are green, and each intended correction names the later
slice and interface that will own its strict contract.

### 2. Complete output-role composition

Extend shared output templates only as far as required to compose through
existing union and parameterized expressions. Make compiler lowering choose an
explicit role for:

- concrete type;
- structural case test;
- type output template;
- field-name expression.

Keep `Literal["x"]` contextual: field names lower to `FieldName`; type outputs
remain standard typing literals.

Completion criterion: `set[Value] | None`, `tuple[Value | None]`, field renames,
and Literal case tests, predicate operands, and outputs all lower according to
their field-name or schema-type role without opaque `NamedType("Value")` leaves.

### 3. Compose possible output types

Add one shared semantic operation that obtains a possible type from either:

- `ResolvedType`; or
- `DeferredMap.possible_output`.

Use it when aggregating deferred outputs, union-subject outputs, and any later
indeterminate outputs. Preserve existing modeled failure messages for genuinely
non-type outputs.

Completion criterion: nested deferred Maps contribute their normalized possible
output once, and adapter failures or non-type outputs retain their established
`SemanticIssue`.

### 4. Model unresolved static type identity

Make a focused domain decision before implementation. The shared model must
represent an authored type whose backend representation exists but whose
concrete identity is unresolved. It must remain distinct from `InputReference`.

The model must retain:

- symbolic identity, so the same unresolved parameter compares equal to itself;
- resolution state per parameterized argument;
- enough provenance for nested expressions to remain indeterminate when used by
  later predicates.

Completion criterion: model-level contracts distinguish two unresolved symbols,
preserve same-symbol identity, retain resolved and unresolved arguments within
one nested parameterized type, and preserve provenance through nested values.
Architecture tests prove `typeforge.semantics` imports no compiler types or
compiler control data.

### 5. Add three-way condition and pattern decisions

Teach shared evaluation to propagate true/match, false/mismatch, and
indeterminate through:

- `Equal` and `Assignable`;
- the full three-way truth tables for `All`, `Any`, and `Not`;
- decisive and failing operands after short-circuit points;
- exact cases;
- parameterized structural patterns;
- repeated capture reconciliation.

For an indeterminate ordered case, combine that case's possible output with only
the recursively reachable remainder. Preserve definite earlier matches and
known structural mismatches.

Completion criterion: all strict unresolved-generic contracts at the shared
`evaluate()` interface pass without xfails, including condition truth tables,
decisive and failure short-circuiting, same-symbol identity, partial structure,
repeated capture, and nested predicates. Ordered Map contracts include
indeterminate then indeterminate then default, indeterminate then definite match
with unreachable later cases, and indeterminate without a default. End-to-end
compiler correction contracts remain assigned to slice 8.

### 6. Preserve schema alias source and expansion

Keep callable relationship aliases on the existing `MapType` lane while
retaining authored semantic source for schema evaluation. Build and test source
alias binding and expansion separately from schema evaluation.

Expansion must bind generic arguments, recurse through every composite source
expression, preserve omitted default versus explicit `Default[Never]`, support
nested aliases, and report cycles in authored terms. Interfaces that resolve
aliases must require alias context rather than defaulting to an empty table.

Completion criterion: adapter-level tests cover every source-expression variant,
nested application/union/starred/Schema placement, generic substitution,
omitted and explicit-Never defaults, nested aliases, and cycles; callable alias
IR and its existing consumers are unchanged.

### 7. Build the compiler schema adapter

Add a compiler-owned adapter that performs:

```text
authored Schema expression
    -> source alias expansion
    -> shared semantic lowering
    -> shared evaluation
    -> ResolvedType or possible output
    -> compiler typing emission
```

Test this adapter directly; do not route production compiler or overlay
boundaries through it in this slice. Convert expected lowering and semantic
failures once into authored `AdaptationError` diagnostics. Use one tested
`StaticType` emission policy, including both bare `Never` and qualified
`tf_typing.Never` contexts.

Completion criterion: adapter-level direct, aliased, structural, deferred,
generic, nested-type, and record-reference contracts pass; failure tests cover
the authored-diagnostic conversion boundary; emission tests cover both `Never`
spellings; source-architecture checks identify the sole semantic-failure
conversion function and confirm no duplicate `StaticType` emission traversal;
callable Map overload and verification tests remain unchanged.

### 8. Cut over and delete the duplicate path

Route every compiler schema boundary through the tested schema adapter. Update
the overlay only as a downstream caller where deletion changes the compiler
interface it consumes. Activate the compiler end-to-end correction contracts
assigned here by the characterization matrix. Then delete from
`_pipeline_adaptation.py`:

- `resolve_schema_type()` and `_resolve_schema_map_member()`;
- `_match_schema_pattern()`;
- `_substitute_schema_capture()`;
- `resolve_schema_predicate()`, `_schema_assignable()`, and unresolved-variable
  detection;
- `union_types_for_schema()`;
- the direct `RuntimeInputType` output-union path.

Do not retain the previous path as fallback behavior.

Completion criterion:

- all compiler schema boundaries use the adapter;
- the overlay no longer calls deleted compiler helpers and its existing
  compatibility tests remain green;
- the public generated-stub contract remains green, including
  `Case[list[Value], set[Value]] -> set[int]`;
- all compiler end-to-end correction contracts pass without xfails;
- callable Map lowering and implementation verification remain green;
- no second structural matcher, predicate evaluator, union normalizer, or
  possible-output calculation exists in the compiler;
- `grep` finds no deleted helper definitions or callers;
- `make check` passes;
- the final cutover diff is predominantly wiring and deletion because semantic
  prerequisites landed in earlier commits.

## Guardrails

- Semantics owns Typeforge meaning; compiler code owns source adaptation and
  standard typing emission.
- `TypeSystem.inspect()` and `build()` remain primitive parameterized-type
  operations. They do not know about Map, Case, Value, captures, or uncertainty.
- Runtime `Input` and unresolved static type parameters remain distinct domain
  concepts.
- Possible output calculation occurs once in shared semantics.
- Source alias adaptation must not round-trip through callable `MapType` IR.
- Diagnostics use authored vocabulary and source expressions, not semantic model
  class names.
- Unsupported variants fail explicitly; no wildcard fallback may erase a newly
  added source-expression variant.

## Deferred runtime decision

A later Pydantic task must define how runtime integration resumes a
`DeferredMap` when input becomes available, including whether selection observes
only input type or also raw value. This compiler roadmap does not make that
runtime decision.
