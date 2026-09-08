# Map slice syntax migration

Status: In progress — feasibility POC, authoring contract, union investigation,
public runtime construction, source normalization, predicate alias binding,
inline checker projection, callable publication, Pydantic integration, and field
composition and diagnostic/tooling integration complete. The authoring cutover
and remaining semantic gates are open.

Next slice: 11 — documentation/caller migration and authoring cutover. Confirmed contract:
None and empty endpoints are equivalent; old authoring is removed at cutover;
string selectors require Literal until tooling supports bare strings.

Contract: [Authoring and migration rules](map-slice-syntax-contract.md).
Union evidence and gates: [Slice 02 findings](map-slice-union-findings.md).

Created: 2026-09-07

Evidence: [Slice Map POC](../ideas/map-slice-poc.md), branch
`neil/map-slice-poc`, commit `08d940a`.

Design constraints: [DESIGN.md](../../DESIGN.md).

## Outcome and scope

Developers express ordered type relationships with one `Map` and
`selector: output` branches:

```python
type Encoded[T] = Map[
    T,
    int: str,
    Assignable[bytes]: str,
    ...: T,
]
```

Concrete selectors use exact matching by default. Structural selectors retain
their existing capture behavior. Unary predicates receive the enclosing Map's
subject. The same authoring syntax must work for supported static compiler uses
and runtime Pydantic integration uses, with their existing policy differences.
There is no separate `If` operator.

Scope includes source parsing, runtime annotation construction, alias-aware
predicate binding, checker overlays, published interfaces, existing MapFields
composition, diagnostics, tooling guidance, and migration of the public surface.
The proposed `Fields`/`On` field-edit interface is a separate follow-up.

Reuse existing source expressions, normalized markers, stub IR, semantic
expressions, and evaluator operations after normalization. The POC demonstrates
that this is feasible for the exercised cases; it does not establish every alias
or union interaction. Do not add a second evaluator or force an unresolved
distinction into an existing model that cannot represent it faithfully.

Preserve valid Python, compiler isolation from authored execution, standard
checker output, finite-specialization honesty, and authored diagnostic locations.
Annotation normalization must not add work to ordinary application call paths.

## Progress checklist

- [x] **00 — Establish feasibility and record integration limits.**
- [x] **01 — Settle the authoring and migration contract.**
- [x] **02 — De-risk union behavior across both frontends and consumers.**
- [x] **03 — Implement production runtime marker construction.**
- [x] **04 — Normalize source slices into existing compiler data.**
- [x] **05 — Bind predicates through aliases and nested scopes.**
- [x] **06 — Project inline annotations for checker overlays.**
- [x] **07 — Complete callable and published-stub integration.**
- [x] **08 — Complete Pydantic integration and runtime dispatch.**
- [x] **09 — Preserve existing field-mapping composition.**
- [x] **10 — Complete diagnostics and authoring-tool compatibility.**
- [ ] **11 — Migrate documentation and callers; retire prototype code.**

Mark a slice complete only when its acceptance criteria and required checks pass.
Record the implementation commit, focused checks, and any remaining follow-up
under that slice. A POC test asserting an existing failure is evidence of a
limitation, not evidence that the corresponding production behavior is complete.

**Union rule:** any slice that parses, constructs, binds, evaluates, projects,
emits, validates, or documents unions must be de-risked before its behavior is
treated as settled. Each affected slice below identifies its specific exposure.
If union scope expands during implementation, add a de-risking note to the new
slice as well.

## Slice details

### 00 — Establish feasibility and record integration limits

Completed by the POC. Its 58 cases exercise successes and known limitations;
focused checks and full `make check` passed at `08d940a`.

Established: slices can normalize into existing Case/Default and predicate data;
generated stubs and named-alias overlays work with mypy, Pyright, and Pyrefly;
early runtime normalization supports the exercised Pydantic generic and dispatch
cases without changing its frontend or evaluator.

Outstanding findings are assigned below: hidden runtime type parameters (03),
unary predicate aliases (05), inline overlays (06), None ambiguity (01), and
bare-string lint behavior (10). Union investigation and remaining gates are
recorded in 02.

### 01 — Settle the authoring and migration contract

Dependencies: 00.

Define selector roles, output roles, exact versus structural matching, explicit
binary predicates, implicit unary predicates, compound conditions, first-match
ordering, and the final `...:` fallback. Preserve the distinction between an
omitted fallback and an explicit `Never` output.

Decide the public rules for None endpoints, omitted endpoints, slice steps
(including explicit third-endpoint None), and bare literal selectors. Runtime
slices erase distinctions that the AST retains; the contract must acknowledge
that instead of promising impossible diagnostic parity. Decide how string
selectors differ from forward references in type positions.

Specify the production relationship between the public Map constructor, canonical
marker identity, and ordinary fallback typing. Record whether legacy
Case/Default authoring is removed at cutover or supported temporarily; temporary
support must have identified consumers and a removal condition. Internal
Case/Default data can remain regardless of public spelling.

Acceptance: a shared behavior matrix with supported, rejected, and deferred forms;
named owners for unresolved decisions; no migration promises based solely on
valid Python parsing.

**Needs de-risking — unions:** selector unions, subject unions, output unions,
and indeterminate alternatives are separate questions. Carry provisional rules
to 02 before accepting them as the language contract.

Completed: [Authoring and migration contract](map-slice-syntax-contract.md).
D1 (None/empty endpoints are equivalent), D2 (remove old authoring), and D3
(require Literal for string selectors) were confirmed by Neil. The supported,
rejected, and deferred behavior matrix and module responsibilities are recorded;
union hypotheses remain assigned to slice 02. The POC's None rejection and bare
string acceptance are evidence of an experiment, not the production contract.
Validation passed: document links, Python example syntax, endpoint equivalence,
decision consistency, and full `make check`. No production behavior or tests
changed.
Commit: pending; contract recorded in the working tree.

### 02 — De-risk union behavior across both frontends and consumers

Dependencies: 01's provisional contract.

Run bounded experiments comparing slice spelling with canonical existing
expressions. Cover the following positions explicitly:

- A subject such as `Map[int | str, ...]`: distribution, per-member case order,
  defaults, and unmatched members.
- A selector such as `int | str`: exact union identity versus matching individual
  members; do not assume these are equivalent.
- Predicate operands such as `Assignable[int | str]` and
  `Equal[int | str]`, including compound predicates.
- Outputs such as `str | None`, parameterized outputs containing unions, and
  union members containing a Map, including `Map[...] | None`.
- Unions reached through aliases, unresolved type parameters, captures, nested
  Maps, and contextual field values.
- Definite union outputs versus possible outputs from indeterminate selection,
  `Any`, explicit `Never`, and no-match paths.
- Deferred Input selection and union-valued output validation/serialization;
  output validation must not resume Map selection.

Exercise source lowering, runtime construction and generic substitution,
published stubs, overlays, Pydantic schemas, and the real checkers where applicable.
Separate syntax regressions from existing representation or policy limitations.

Acceptance: record expected outcomes and executable evidence for each position;
identify supported forms and explicit restrictions; assign unresolved work to a
bounded follow-up or implementation slice. Do not mark this complete with only
parser acceptance or a blanket assertion that unions work.

**Needs de-risking — unions:** this entire slice is the required investigation.
Its accepted matrix is a prerequisite for union-bearing work in later slices.

Completed investigation: [Union matrix and follow-up gates](map-slice-union-findings.md).
Added 85 executable cases comparing old and slice spellings through static Schema
output, runtime schemas, generic substitution/rebuilds, Input validation and
serialization, indeterminate provenance, record materialization, and published
stubs/named-alias overlays using all three checkers. No production code changed.

No syntax-specific union regression was found in this matrix. Existing consumer
differences remain gated: selector/predicate/callable meaning (G1), compiler union
equality ordering (G2), runtime alias opacity (G3), Any absorption (G4), and field
distribution (G5). Unsupported record unions and union capture patterns remain
explicit limits (G6). Constructor/projection evidence carries forward under G7.
The report assigns each gate to its owning slice; semantic changes require
agreement before implementation. Completing this investigation does not mark
those production fixes complete. Slice 03 can proceed with normalization alone.

Validation passed: 85 new cases, focused `make check`, full `make check`
(pytest, Ruff lint/format, block spacing, mypy, Pyright), document links, and
Python example parsing. Real mypy/Pyright/Pyrefly probes run within the new suite.
Commit: pending; evidence recorded in the working tree.

### 03 — Implement production runtime marker construction

Dependencies: 01; 02 for union-bearing construction.

Convert slices to canonical existing marker arguments before Python or Pydantic
performs generic substitution. Preserve parameters appearing only in selectors
or outputs, ordinary parameter discovery, specialization, and marker recognition.
Replace the POC's separately imported facade with the agreed public constructor
and canonical-identity arrangement.

Keep construction declarative: allocate annotation data without evaluating
relationships, invoking authored callbacks, or performing validation. Base
Typeforge imports must remain independent of optional Pydantic dependencies.

Acceptance: public imports construct the intended canonical data; named aliases,
direct generic model annotations, output-only type parameters, hashing/equality,
and specialization retain known information. Cover malformed subscriptions and
the agreed compatibility and fallback behavior.

**Needs de-risking — unions:** generic discovery and substitution must traverse
union-bearing selectors and outputs; verify combining the constructed marker
with a union outside the subscription.
Use slice 02's generic substitution/rebuild evidence and gate G7 as the baseline.

Completed: public runtime `Map` now delegates to the inert constructor in
[`_map.py`](../../src/typeforge/_map.py). Subscriptions return the existing
`_markers.Map` alias with Case/Default arguments. Pydantic recognizes that
canonical identity; checker imports retain the canonical object fallback.
The evaluator and union matching semantics were not changed.

The constructor preserves output-only and selector-only parameters, same-named
parameters from distinct scopes, unions inside branches and outside Map, nested
Maps, structural patterns, and metadata. Inline unary predicates bind locally;
explicit operands remain explicit. None endpoints normalize to NoneType (including
empty endpoints), non-None steps fail, direct defaults must be last, and bare
string selectors require Literal. Construction does not expand authored aliases
or evaluate semantic failures.

Legacy Case/Default entries and aliases remain for the existing repository
consumers until the coordinated slice-11 removal. Aliased legacy branch validation
still belongs to frontend expansion; the constructor does not inspect alias bodies.
Frontend tests inject malformed canonical data directly where public construction
now rejects it earlier. The POC facade remains historical evidence until slice 11;
production callers do not need its import.

Evidence: [28 public construction cases](../../tests/unit/runtime/test_map_construction.py)
and an [isolated import/construction test](../../tests/unit/runtime/test_imports.py)
with site packages disabled. Generic Pydantic aliases and direct model fields
specialize and rebuild. Equality/hash behavior, inert object fallback, metadata,
branch order, no-match/Never, and malformed construction are covered. The initial
output-only tracer was observed failing before implementation and now passes;
no expected-failure markers remain for slice 03.

Validation passed: focused `make check` across construction, runtime integration,
union evidence, and architecture; full `make check` (pytest, Ruff lint/format,
block spacing, mypy, Pyright). Public README/marker docs and DESIGN were updated.
Source normalization (04), alias-aware binding (05), inline overlays (06), and
slice-02 semantic gates retain their existing owners.
Commit: pending; implementation is in the working tree.

### 04 — Normalize source slices into existing compiler data

Dependencies: 01; 02 for union-bearing syntax.

Recognize slices only in the appropriate imported Map context. Normalize entries
to existing source Case/Default representations and preserve authored text and
spans. Handle literal selectors and inline implicit predicates according to the
contract. Validate ordering, duplicate defaults, arity, and malformed endpoints.

Keep normalization role-aware: concrete matching and structural capture must not
be collapsed into the same boolean equality operation. Reuse source parsing and
normalization owners; do not reparse source in downstream consumers.

Acceptance: equivalent old/new forms produce equivalent downstream data and
generated interfaces; qualified imports and renamed imports work; unsupported
forms produce typed, located failures. None and empty endpoints follow the
confirmed equivalence rule; string selectors require Literal. Prove the compiler
never imports or executes authored application code.

**Needs de-risking — unions:** preserve grouping, selector/output roles, nested
union syntax, and source locations. Syntactic normalization must not itself
invent union membership or distribution semantics.
Carry G2's resolved-equality mismatch separately from syntax normalization.

Completed: the production source parser normalizes slices into existing
MarkerTypeExpression Case/Default data. None and empty endpoints emit the same
interface; an explicit None step is inert. Selector literal sugar and inline
predicate binding preserve structural patterns, explicit operands, nested subject
scope, output roles, and union grouping.

The parser now returns located SourceSyntaxError results for non-None steps,
branches after a fallback (including mixed legacy entries), bare string selectors,
and a slice where the subject is required. Errors use authored AST spans,
including UTF-8 columns. Synthesized None endpoints are anchored to their branch;
the branch retains its exact source spelling. General marker arity and entry-role
validation remain with the existing normalization owner. No source data model,
evaluator, or union matching semantics changed.

Evidence: [34 source contracts](../../tests/unit/compiler/source/test_map_slices.py)
cover generated-interface equivalence, qualified/renamed imports, unrelated
subscriptions, nested scopes, output strings, union roles, sentinel outcomes,
located failures, and compiler isolation from authored execution. Obsolete POC
None-rejection tests were replaced by these contracts; compiler POC string
examples now use Literal. The separate runtime POC and its import recognition
remain historical consumers pending slice 11.

Validation passed: focused `make check` (185 tests including the union matrix,
Ruff lint/format, block spacing, mypy, Pyright), full `make check`, and diff
whitespace checks. README and DESIGN describe source normalization. Alias-aware
binding (05), inline projection (06), diagnostics beyond this syntax boundary
(10), and union gate G2 retain their owners. No expected-failure markers were
introduced or left pending for this slice.
Commit: pending; implementation is in the working tree.

### 05 — Bind predicates through aliases and nested scopes

Dependencies: 03, 04, and the applicable 02 outcomes.

Support reusable unary predicate aliases such as `type Numeric = Assignable[int]`
in Map selector positions. Coordinate normalization with existing alias expansion
before binary-predicate arity validation. Cover generic aliases, explicit binary
predicates, compound conditions, and unsupported or recursive alias forms.

Define and test which enclosing subject a predicate uses. A nested Map establishes
its own subject; siblings must not leak bindings. Preserve authored type-symbol
identity and the existing distinctions between the Map subject, structural
captures, field Key/Value, and runtime Input.

Acceptance: equivalent inline and aliased predicates behave consistently in
static and runtime frontends and lower to existing predicate data. Failure
propagation, alias-cycle behavior, and authored provenance remain deliberate.

**Needs de-risking — unions:** aliases may hide unions or unresolved alternatives.
Verify binding before/after expansion does not alter branch reachability,
distribution, or capture meaning.
Resolve slice 02 gates G1/G3 before claiming portable union predicate/alias behavior.

Completed: both frontends bind unary predicate aliases at the consuming Map.
Source alias expansion reuses the selector normalizer before arity validation;
callable and record adaptation selectively expand predicate aliases while their
ordinary type-alias policies remain unchanged. Runtime adaptation carries the
selector subject through aliases and compound conditions. Alias declarations
remain reusable and unbound; explicit binary operands and output positions do
not inherit a selector subject. Existing semantic expressions and evaluators are
unchanged.

Evidence: [16 compiler cases](../../tests/unit/compiler/adaptation/test_source_predicate_aliases.py)
and [17 runtime cases](../../tests/unit/pydantic/test_predicate_aliases.py) cover
generic type arguments, chained and compound aliases, nested and sibling Maps,
same-named type parameters, explicit operands, Key/Value, structural captures,
Input selection without retry, malformed uses, cycles, authored origins, metadata,
and compiler isolation. Initial runtime and compiler alias tracers failed before
implementation; the record tracer also exposed and verified its missing seam.
Obsolete POC failure assertions now verify success. Existing failure-propagation
tests use three-operand predicates because unary selectors are now valid.

Union de-risking is bounded: aliased Assignable predicates with union operands
match inline predicates for concrete and union subjects in each frontend; source
outputs also contain unions. The existing 85-case union matrix still passes.
This establishes binding parity, not cross-consumer union equivalence. Ordinary
union-alias opacity, selector distribution, and G1/G3 remain assigned to 07/08.
Generic predicate examples accept type arguments; higher-order unbound predicate
parameters are outside this slice's supported examples. Existing frontend limits
for unsupported generic and recursive aliases remain explicit.

Validation passed: focused checks across compiler, Pydantic, construction, and
union evidence; full `make check` (pytest, Ruff lint/format, block spacing, mypy,
Pyright), and diff whitespace checks. README, DESIGN, and the contract were
updated. No expected-failure markers remain for this slice.
Commit: pending; implementation is in the working tree.

### 06 — Project inline annotations for checker overlays

Dependencies: 04, 05, and applicable 02 outcomes.

Replace supported inline slice-bearing annotations with ordinary checker types in
the generated document, including supported nested positions. Reuse retained
contracts, existing fallback emission, and source mappings. Preserve the authored
relationship for implementation verification and leave authored files untouched.

Acceptance: mypy, Pyright, and Pyrefly accept both inline and alias-based overlays,
infer mapped call results, and reject incorrect implementation returns. Check
direct/nested annotations, methods, idempotence, source mapping, and diagnostic
locations. Raw slices must not survive in checker-visible type arguments for a
supported use.

**Needs de-risking — unions:** aggregate fallback types and projected annotations
can contain unions even when no `|` appears in the source. Verify reachable
outputs, explicit Never, no-match behavior, and definite versus speculative
results before choosing the projected type.
Carry slice 02's provenance/checker evidence forward under G7.

Completed: adaptation retains inline Map roots using existing reusable elements
and authored origins. Source facts now include assignment annotations for module
and local variables. Overlay projection replaces parameters, returns, fields,
variables, nested alias values, and generated overload annotations with ordinary
typing expressions. Both slice and canonical spellings use this path. Authored
callable contracts remain intact for implementation verification.

The existing checker fallback and stub-IR child traversal own type projection;
there is no new evaluator. Overlapping Schema/Map roots produce one outer edit.
UTF-8 authored columns convert correctly to character offsets. Publication keeps
its existing record-field and variable-surface policies. Source text remains
untouched, and projection consumes the completed plan without parsing or compiling
again.

Evidence: [17 overlay cases](../../tests/unit/overlay/test_inline_maps.py) exercise
direct and nested annotations, methods, predicate aliases, variables, qualified
imports, ordinary value slices, source isolation, idempotence, Unicode spans,
diagnostic provenance, and union fallback policies. Three new real-checker cases
accept nested union annotations and reject wrong implementation returns. The
POC's three inline checker rejection cases now assert success and wrong-return
rejection alongside the existing alias/stub cases.

Union de-risking: inline fallback remains the conservative union of declared
outputs and fallback, including explicit Never and unmatched-subject alternatives;
Schema selects/evaluates separately. Union outputs, nested Maps, and nested alias
unions project without conflating those policies. The original 85-case union
matrix passes. This closes slice 06's G7 projection work, not G1–G6 or remaining
publication/runtime obligations. An Assignable/isinstance verification probe
retains the same conservative extra fallback obligation in both spellings;
its precision belongs to 07.

Validation passed: focused compiler/overlay checks, real mypy/Pyright/Pyrefly
probes, full repository checks (pytest, Ruff lint/format, block spacing, mypy,
Pyright), and diff whitespace checks. README, DESIGN, and the contract were
updated. No expected-failure markers were introduced or left pending.
Commit: pending; implementation is in the working tree.

### 07 — Complete callable and published-stub integration

Dependencies: 04, 05, and applicable 02 outcomes.

Exercise existing callable specialization and publication with slice syntax:
exact/literal selectors, assignability, compounds, supported captures, aliases,
defaults, and existing finite Each/Collect composition. Preserve deterministic,
complete interfaces derived from library source and configuration.

Acceptance: generated stubs contain only portable typing syntax, and consumers
using all three checkers infer the expected types without running Typeforge.
Unsupported relationships fail honestly. Published and overlay fallback policies
retain their intentional differences.

The POC's unbounded `list[Value]` callable emission failure also occurs with old
syntax. Track it explicitly as existing callable-lowering follow-up work unless
resolving it becomes an agreed prerequisite; do not silently claim it is fixed
by this syntax migration. Unifying callable semantics is separately tracked in
[Callable Map semantics cutover](../ideas/callable-map-semantics-cutover.md).

Slice 06 also records an existing conservative verification limit: an Assignable
predicate combined with an isinstance guard may require the fallback output on the
guarded return as well. Exact Equal/type guards have successful checker evidence.
De-risk this predicate/guard interaction before expanding callable precision.

**Needs de-risking — unions:** overload inputs/outputs, branch overlap, inferred
fallbacks, and finite specialization of union subjects need checker evidence,
not just emitted-text comparisons.
Resolve or explicitly constrain G1/G2/G4; the slice 02 overloads are checker-valid
but do not always agree with static Schema selection.

Evidence: [Production publication regressions](../../tests/unit/compiler/pipeline/test_slice_publication.py),
13 passing cases, including six real-checker cases across two finite frontiers.
Consumers check generated stubs after removing authored source; an incorrect
assert_type must fail. Coverage includes exact/literal selectors, assignability,
compounds and predicate aliases, defaults, union outputs, finite structural
captures, complete interfaces, deterministic publication, and typed unsupported
relationship failures. Published aliases and overlay bounds retain their distinct
policies. Existing compiler stages handle these forms without a production change.

**Union de-risking outcome:** G1/G2/G4 are explicitly constrained by the
[publication boundary](map-slice-union-findings.md#slice-07-callable-publication-boundary).
Positive evidence covers union outputs, captured unions, union-argument aggregate
bounds, and configured finite captures. Cross-consumer selector equivalence,
order-independent equality, Any selection, and unbounded captures remain gated.
The Assignable/isinstance verification limit and compound predicate candidate
precision remain with the separate callable semantics cutover.

Validation: focused publication, source POC, inline overlay, and union matrix
checks passed. Full `make check` passed: pytest, Ruff lint/format, Flake8 block
spacing, mypy, and Pyright.
Commit: pending.

### 08 — Complete Pydantic integration and runtime dispatch

Dependencies: 03, 05, and applicable 02 outcomes.

Exercise public slice syntax through Schema, TypeAdapter, generic models,
specialization, inheritance, rebuilds, annotations, and deferred Input. Reuse
shared evaluation and Pydantic's validation, metadata, and serialization owners.

Acceptance: equivalent canonical/slice forms produce the expected schemas and
values; no-match and explicit Never remain distinct; generic fallback policies,
unsupported runtime patterns, short-circuiting, and first-match behavior remain
correct. A selected output's validation failure must never retry another branch.
Schema-time normalization adds no validation callbacks.

**Needs de-risking — unions:** test generic union fallbacks, deferred bounds,
union output schemas, validation ambiguity, and serialization. Preserve possible
output provenance and do not infer authored static type arguments from values.
Resolve G1/G3/G4 and promote G7 evidence through the public constructor.

Evidence: [Runtime lifecycle](../../tests/unit/pydantic/test_runtime_pipeline.py)
and [deferred dispatch](../../tests/unit/pydantic/test_deferred_pipeline.py)
regressions now author public slices, retaining their prior acceptance assertions.
The [85-case union matrix](../../tests/unit/test_slice_union_matrix.py) uses the
public constructor rather than the prototype. [Nine additional cases](../../tests/unit/pydantic/test_slice_integration.py)
cover empty/None endpoints, Literal selectors, output metadata and references,
and ordinary alias roles. The focused suite has 136 cases. No production change
was required; existing frontend normalization and shared evaluation handle them.

**Union de-risking outcome:** G7's runtime promotion is complete. G1/G3/G4 retain
existing policy with the explicit [runtime support boundary](map-slice-union-findings.md#slice-08-runtime-integration-boundary).
Bare selectors, whole-subject predicates, and Input observation keep distinct
roles. Transparent static alias matching and Any-containing union selection
remain outside cross-consumer guarantees. No semantic convergence is claimed;
the broader differences remain follow-ups. Field distribution stays with 09.

Validation: focused runtime/union checks passed. Full `make check` passed:
pytest, Ruff lint/format, Flake8 block spacing, mypy, and Pyright.
Commit: pending.

### 09 — Preserve existing field-mapping composition

Dependencies: 03–05, 07–08, and applicable 02 outcomes.

Use slice Maps inside existing MapFields with contextual Key/Value, field-name
selectors, predicates, nested value Maps, dropping, renaming, and explicit field
modifiers. Cover static record materialization and runtime Schema use.

Acceptance: equivalent expressions retain existing field types, requiredness,
readonly behavior, metadata, duplicate-name failures, and supported-record-family
restrictions. In particular, existing `Field[Key, Value]` remains required and
writable; this task does not introduce the proposed preservation-by-default
field-edit semantics.

**Needs de-risking — unions:** field values and nested outputs can be unions.
Keep field names distinct from Literal value types, and verify existing rejection
or support for speculative field results and record-union operands.
G5 records a concrete compiler/runtime distribution mismatch; G6 records existing
record-union and union-capture restrictions. Neither is fixed by the POC.

Evidence: [13 field integration cases](../../tests/unit/test_slice_fields.py)
cover canonical/slice publication parity, runtime values and schemas, key versus
Literal value roles, predicate aliases, dropping, renaming, explicit modifiers,
union outputs, typed failures, and indeterminate field-layout rejection. All three
checkers accept generated field types and reject readonly mutation. Existing
[record](../../tests/unit/pydantic/test_records.py) and
[field](../../tests/unit/pydantic/test_map_fields.py) suites now use slices for
their Map relationships, preserving metadata, rebuild, and failure assertions.
No production changes were required.

**Union de-risking outcome:** plain union-valued fields and union outputs have
positive runtime and checker evidence. G5's nested field-union distribution
mismatch is explicitly constrained, not fixed; G6 retains record-union and union
capture-pattern rejection. Deferred and indeterminate field layouts remain
unsupported. See the [field support boundary](map-slice-union-findings.md#slice-09-field-composition-boundary).

Metadata follows existing consumer policy: the compiler projects Annotated field
types to their base type, while Pydantic retains constraints and record metadata.
An inherited-record callable probe also exposed existing broader-first overload
ordering rejected by mypy; generated record-type checks exclude that unrelated
callable and do not establish inherited dispatch precision. The follow-up is
recorded alongside G5/G6.

Validation: focused field/runtime/union checks passed. Full `make check` passed:
pytest, Ruff lint/format, Flake8 block spacing, mypy, and Pyright.
Commit: pending.

### 10 — Complete diagnostics and authoring-tool compatibility

Dependencies: 01 and the integration behavior established in 03–09.

Update diagnostics to describe authored slice syntax rather than internal
Case/Default encodings. Preserve authored locations through normalization, alias
expansion, specialization, projection, and runtime error translation.

Enforce the confirmed Literal requirement for string selectors and give an
actionable diagnostic for bare strings. Record acceptable formatting and the
tooling evidence required before revisiting that restriction. No lint workaround
is required for the initial supported spelling; do not silently disable unrelated
checks. Explain accurately when authored annotations require Typeforge processing
rather than claiming every valid Python expression is a checker type.

Acceptance: malformed and unsupported forms have actionable diagnostics; lexer,
formatter, linter, and checker probes cover representative documented examples;
static/runtime differences follow the recorded contract.

**Needs de-risking — unions:** failures within union members and branches must
point to authored expressions and preserve whether the failure is definite,
speculative, or an unsupported representation. Formatting must retain grouping.

Evidence: [12 diagnostic regressions](../../tests/unit/test_slice_diagnostics.py)
and [four tooling probes](../../tests/unit/test_slice_tooling.py). Compiler/runtime
branch messages now use the public syntax. Runtime issue display renders canonical
Map data as slices while preserving aliases, literal/metadata payloads, issue
codes/phases, subjects, and validation locations. Unicode spans inside nested
union branches and authored literal expressions through predicate aliases remain
covered. Existing message assertions were updated at their consumers.

Python tokenization/parsing and Ruff formatting preserve the supported fixture's
AST, including unions and empty endpoints. It passes the repository's Ruff rules.
All three checkers reject the raw fixture, accept its Typeforge overlay, and
reject a wrong implementation return. Bare strings still produce Ruff F821;
Literal remains required. No lint configuration or line-length changes were made.
See the [tooling guidance](map-slice-tooling.md) for versions and scope.

**Union de-risking outcome:** grouping, source spans, runtime error locations,
and presentation of nested annotations are covered. Existing semantic error and
provenance boundaries remain unchanged; this slice does not resolve G1–G6.

Validation: focused checks and full `make check` passed: pytest, Ruff lint/format,
Flake8 block spacing, mypy, and Pyright.
Commit: pending.

### 11 — Migrate documentation and callers; retire prototype code

Dependencies: 01–10.

Make slice Map the documented authoring surface. Update README examples, marker
documentation, fixtures, integration examples, and public syntax/design guidance.
Apply the agreed legacy-syntax policy; migrate affected callers and remove
superseded helpers, imports, and exports within scope. Any retained compatibility
path needs a named consumer or removal condition.

Promote useful POC assertions into production regression coverage, replacing
known-failure characterizations where the corresponding issue is resolved. Remove
the runtime prototype facade, demo, and parser hooks after their consumers have
migrated; retain the feasibility report and branch/commit as historical evidence.

Acceptance: public examples run; focused checks and full `make check` pass; the
final diff has no unrelated changes; remaining limitations are explicitly linked
to follow-up work. Review documented claims against the accepted behavior matrix.

**Needs de-risking — unions:** publish union examples only after the corresponding
02 matrix entries and consumer checks pass. Do not let documentation turn a
finite or speculative result into a claim of open-ended generic support.

Evidence/commit: pending.
