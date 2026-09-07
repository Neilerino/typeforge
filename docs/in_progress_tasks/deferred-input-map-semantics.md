# Deferred Map Semantics and Compiler Cutover

Status: In progress — slices 1–5 complete; slice 6 next
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

The compiler refactor through `7314f36` isolated the legacy schema evaluator,
moved shared lowering into `compiler.semantic_adapter`, and made overlays consume
`CompilationPlan`. Slice 1 now characterizes that production baseline in the
[behavior matrix](deferred-input-map-characterization.md), with green retained
contracts and separately recorded corrections. No production semantics changed
in slice 1.

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
  `tests/unit/compiler/semantic_adapter/test_type_system.py` and
  `tests/unit/compiler/semantic_adapter/test_semantic_lowering.py` pass without
  xfails.
- Slice 1's retained production contracts are covered by
  `tests/unit/compiler/pipeline/test_schema_map_characterization.py`. The
  characterization matrix assigns each intended correction to its later owning
  interface and slice.
- Slice 3 composes possible output types for nested deferred Maps, union-subject
  outputs, and explicit union expressions through one shared operation.
- Slice 4's public data model retains scoped type symbols, partial parameterized
  structure, and indeterminate alternatives.
- Slice 2 composes output templates through unions and applications, with explicit
  type, output-template, and field-name roles in compiler lowering. Structural
  case tests use their dedicated pattern lowering path.
- Slice 5 evaluates unresolved static values through three-way predicates and
  structural matches, preserves ordered reachable alternatives and capture
  constraints, and retains uncertainty through nested types and predicates.

### Not cut over

Schema-boundary resolution still runs through compiler stub IR.
`src/typeforge/compiler/adaptation/_source_to_ir.py` expands callable `MapType`
aliases and invokes `adaptation/_legacy_schema.py` at a `SchemaType` boundary.
The legacy evaluator still owns:

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

Shared lowering and the compiler `TypeSystem` now live in
`src/typeforge/compiler/semantic_adapter/`. Record materialization already uses
them; its `_static_type_expression()` is an existing owner of StaticType-to-stub
conversion to consider when unifying emission in slice 7.

Overlay projection consumes the compiler's `CompilationPlan`, including authored
origins and reusable schema roots, rather than calling schema evaluation helpers.
Preserving distinct boundary roots and origins is part of the cutover contract.
Published stubs still use their existing selected source scope; opaque published
record annotations and overlay resolution must retain their intentional difference.

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
- `StaticType` has one conversion policy for emitted `StubTypeExpression`, including
  context-sensitive `Never` spelling;
- expected `SemanticLoweringError | SemanticIssue` failures are converted once
  at a deliberate compiler result boundary;
- schema adaptation preserves authored origins and independent reusable roots
  consumed by `CompilationPlan` projection, including nested Schema and aliases
  whose resolved outputs are equal.

Choose concrete helpers only when the implementation identifies two real
callers. Keep them private supporting adapters rather than new compiler concepts.

## Implementation sequence

Each slice should be independently reviewable and leave `make check` green.
Work test-first from the named interface; avoid combining later slices into the
current one.

### 1. Characterize the production compiler behavior

Complete on the post-refactor baseline. See the
[characterization matrix](deferred-input-map-characterization.md) for retained
test IDs, observed correction cases, their owning interfaces, and existing
compiler-plan compatibility contracts. The requirements below define this slice's
scope and remain the checklist for future discoveries.

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

Slices 2 and 5 have now discharged the lowering and evaluation prerequisites
for C13 and C1–C9 respectively. Their compiler end-to-end correction coverage
remains assigned to slice 8. Next: slice 6's source alias contracts (C10–C12).

### 2. Complete output-role composition

Complete. Shared output templates compose through existing union and
parameterized expressions. `lower_semantic_expression()` accepts a keyword-only
role (`type`, `output`, or `field-name`); structural case tests use the dedicated
pattern lowerer. Compiler lowering chooses the appropriate role for:

- concrete type;
- structural case test;
- type output template;
- field-name expression.

Keep `Literal["x"]` contextual: field names lower to `FieldName`; type outputs
remain standard typing literals.

The contracts in
`tests/unit/compiler/semantic_adapter/test_semantic_lowering.py` cover both union
template positions, Literal case/predicate/output roles, C13's transformed field,
and predicates over a field's Literal type inside a Map over Key. Defaults use
the same output role as cases. No compiler schema boundary has cut over.

Completion criterion: `set[Value] | None`, `tuple[Value | None]`, field renames,
and Literal case tests, predicate operands, and outputs all lower according to
their field-name or schema-type role without opaque `NamedType("Value")` leaves.

### 3. Compose possible output types

Complete. `expect_possible_type()` in shared semantic assertions obtains a
possible type from either:

- `ResolvedType`; or
- `DeferredMap.possible_output`.

Deferred case/default outputs, union-subject outputs, and explicit union
expressions use that operation. It consumes the nested `possible_output` without
re-evaluating cases. Backend union normalization remains behind `TypeSystem`.
Concrete field/record consumers remain separate. Slice 5's comparisons and
parameterized templates retain unresolved provenance rather than reducing those
values to their possible bounds. Extracting a bound does not resume a deferred
selection.

Contracts at `evaluate()` in `tests/unit/semantics/test_migration_spec.py` cover
nested case/default outputs, duplicate normalization, omitted/explicit-Never
defaults, original non-type messages, modeled failure identity and
short-circuiting, and propagation of unexpected adapter exceptions. The name-only
test adapter now honors union flattening and Never elimination for nested bounds.
The strict correcting contracts were removed from xfail in this slice.

Slice 5 extends the same operation to unresolved static values and indeterminate
output bounds while retaining provenance in semantic comparisons.

Completion criterion: nested deferred Maps contribute their normalized possible
output once, and adapter failures or non-type outputs retain their established
`SemanticIssue`.

### 4. Model unresolved static type identity

Complete at the model interface. The decision is to use a scoped `TypeSymbol` for
authored parameter identity, independent of the backend's spelling. `UnresolvedType` retains its
backend value and provenance: either that symbol or an existing
`ParameterizedTypeShape` whose origin and arguments are semantic `TypeValue`s.
Thus `tuple[int, list[T]]` can retain a resolved first argument and the exact
unresolved position within its second argument without teaching `TypeSystem`
about uncertainty.

An `IndeterminateType` retains a possible output bound and its alternative
`TypeValue`s. It is distinct from both a resolved union and a type symbol:
identical alternative lists do not establish that two selections have the same
identity. Nested structures can retain these values rather than replacing them
with their union bound. Ordered selection and normalization of alternatives
belong to slice 5.

These were model-only additions in slice 4. Slice 5 now integrates them through
`TypeValueReference`, evaluation values, contexts, and structural case tests.
`UnionTypeShape` additionally preserves the members of a definite union containing
unresolved positions; such a union is distinct from an indeterminate selection's
alternative results. Model contracts use the package's public data interface;
architecture rules enforce independence from compiler data and control flow.
See [domain terminology](../../CONTEXT.md).

`tests/unit/semantics/test_unresolved_types.py` covers scope identity, nested
resolved/unresolved positions, alternative provenance, backend `None`, and
immutability. Both static checkers also validate that model test file directly.
The existing semantics architecture suite proves that the model imports no
compiler types or compiler control data. The strict model contracts pass without
xfails. Focused semantics/architecture checks and full `make check` pass for
slices 3 and 4.

The model retains:

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

Complete. Shared evaluation propagates true/match, false/mismatch, and an
`IndeterminateCondition` through:

- `Equal` and `Assignable`;
- the full three-way truth tables for `All`, `Any`, and `Not`;
- decisive and failing operands after short-circuit points;
- exact cases;
- parameterized structural patterns;
- repeated capture reconciliation.

For an indeterminate ordered case, combine that case's possible output with only
the recursively reachable remainder. Preserve definite earlier matches and
known structural mismatches.

`tests/unit/semantics/test_indeterminate_evaluation.py` exercises the public
`evaluate()` seam: full truth tables, failure short-circuiting, C1–C9, nested
predicates, repeated-capture reconciliation (including complementary known
positions), unresolved union identity, nested output provenance, and adapter
failure identity. `semantics.type_evaluation` owns shared type relations and
composition; Map matching and predicate evaluation both consume those operations.
All correction contracts pass without xfails. Focused checks and full `make check`
pass; compiler characterization and callable behavior remain green.

An omitted default contributes no possible output type. Its unmatched `Never`
alternative remains in an indeterminate result's provenance so a later predicate
does not mistake its possible bound for a definitely selected result.

TypeSystem still supplies primitive inspect/build operations, not generic
variance or bound rules. Assignability is definite for resolved comparisons and
proven identical static types; other partial generic relationships remain
indeterminate unless union/alternative reasoning decides them. Structural capture
requires known argument positions: `list[T]` supports capturing T, whereas an
opaque T matched against `list[Value]` reports a modeled unsupported-expression
failure instead of inventing an argument type or using an unrelated field binding.

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

Account for the current adaptation contract: generated replacements must retain
authored origins and reusable schema-boundary identity. Reuse the source facts
already supplied to compilation; do not introduce reparsing or evaluation in
overlay projection. The matrix lists the existing contracts to preserve.

Completion criterion: adapter-level direct, aliased, structural, deferred,
generic, nested-type, and record-reference contracts pass; failure tests cover
the authored-diagnostic conversion boundary; emission tests cover both `Never`
spellings; source-architecture checks identify the sole semantic-failure
conversion function and confirm no duplicate `StaticType` emission traversal;
callable Map overload and verification tests remain unchanged.

### 8. Cut over and delete the duplicate path

Route every currently evaluated compiler schema boundary through the tested
schema adapter, preserving publication's selected source scope. The overlay
already consumes `CompilationPlan`; update it only as a downstream caller if the
compiler interface it consumes changes. Activate the compiler end-to-end
correction contracts assigned here by the characterization matrix. Then delete from
`src/typeforge/compiler/adaptation/_legacy_schema.py`:

- `resolve_schema_type()` and `_resolve_schema_map_member()`;
- `_match_schema_pattern()`;
- `_substitute_schema_capture()`;
- `resolve_schema_predicate()`, `_schema_assignable()`, and unresolved-variable
  detection;
- `union_types_for_schema()`;
- the direct `RuntimeInputType` output-union path.

Do not retain the previous path as fallback behavior.

Completion criterion:

- all currently evaluated compiler schema boundaries use the adapter;
- overlay projection still consumes the compiler plan, with authored origins,
  independent reusable schema roots, and its existing compatibility tests green;
- the public generated-stub contract remains green, including
  `Case[list[Value], set[Value]] -> set[int]`;
- all compiler end-to-end correction contracts pass without xfails;
- callable Map lowering and implementation verification remain green;
- no second structural matcher, predicate evaluator, union normalizer, or
  possible-output calculation exists in the compiler;
- `rg` finds no deleted helper definitions or callers;
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
