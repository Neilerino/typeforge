# Compiler analysis and overlay projection plan

Status: In progress, 2026-09-06 — functional seams approved; slices 1–2 authorized
for implementation and review. 2 of 6 slices complete; paused for user review.

This is the active task document for the next compiler scope. The previous
eleven-slice compilation-plan migration is complete and its task document has been
retired. It removed most consumer compilation choreography, but overlay still
parses authored source and verification still adapts annotations again.

Read `AGENTS.md` and `DESIGN.md` before implementation, and
`tests/architecture/AGENTS.md` before changing architecture tests. The current
starting commit is `d81d57e` (`deload more responsibility from overlay to compiler`);
recheck repository state when resuming rather than assuming the checkout is unchanged.

This document records the approved seams, compatibility requirements, six tracked
slices, and completion evidence. The user approved this approach and requested
implementation of the first two slices on 2026-09-06; stop after those slices for
review. That handoff supersedes the draft approval notes below for their scope.

## Existing foundation and compatibility requirements

- `compile_source(source, path, maximum_arity)` currently returns
  `CompilationPlan(source, module)`. Its path is source identity; it does not read
  or execute the authored application. `generate_module` is the path-based entry.
- Adaptation owns record materialization. Specialization consumes and returns
  `StubModule`. Preserve that composition without pipeline-owned rewrite deltas,
  declaration matching by name, or stage-specific wrappers around the module.
- `GeneratedElementOrigin[SourceSpan]` refers to an element reachable by identity
  in the same immutable module snapshot. Preserve one-to-many and many-to-one
  associations, authored-position ordering, and first-occurrence traversal order
  through declarations followed by reusable roots. Ordinary declarations do not
  acquire origins merely because they exist. Failed stages leave inputs unchanged.
- At the start of this scope, `StubModule.expressions` retained reusable alias/schema IR. These roots
  preserve reference forms lost during declaration rewriting, do not emit extra
  declarations/imports, and retain separate schema-boundary identity to prevent
  overlapping edits. The proposed generalization must preserve those contracts.
- Published relationship aliases retain the conservative `object` fallback;
  overlay relationships retain the union-of-outputs fallback. Keep projection
  policy out of annotation interpretation.
- Preserve publication's historical scope selection and opaque TypedDict field
  annotations. Syntax errors precede surface validation; surface failures precede
  adaptation/specialization failures in the path-based publication entry. Runtime
  statements accepted for an overlay can still be unsupported for publication.
- Pipeline-owned authored callable descriptions already travel on
  `VirtualDocument.authored_callables`. Preserve selection, qualified names,
  parameter kinds/defaults, annotation spelling, and diagnostic text without
  reparsing. Identity documents after compilation retain descriptions; the
  generated-source sentinel and invalid-arity checks remain early exits.
- Malformed Typeforge markers in class fields/bases already return typed adaptation
  errors by explicit approval, including `value: Map[int]` and
  `class Payload(Each[int, str]): ...`. Preserve this current behavior.
- Source syntax, adaptation, record materialization, and specialization failures
  remain modeled compiler results. Surface and emission failures retain their
  respective owners. Do not return a partial successful compilation plan.

The previous migration's compiler/overlay/diagnostic contracts are ordinary passing
tests. The unrelated `tests/unit/frontends/test_stubpy.py` xfail remains outside this
scope. Use repository tests as the durable baseline; temporary review artifacts
from earlier sessions are not prerequisites for this task.

## Outcome and scope

One compiler invocation parses one authored source snapshot once. The compiler
interprets its annotations and analyzes implementation checking obligations.
Overlay consumes the resulting plan to generate text and source mappings.
Diagnostics consume authored descriptions and provenance.

The public plan contains Typeforge-owned source facts, generated typing IR, and
verification obligations. It does not expose a Python AST. An AST may be used
inside the compiler while compilation is running.

Preserve generated text, mappings, diagnostic presentation, supported verification
flow, conservative degradation, and modeled failures, including the previously
approved malformed-class-marker validation. This is a responsibility migration,
not an expansion of what Typeforge can infer about Python implementations.

The existing `StubModule` representation, immutable snapshots, current-element
origins, and adaptation ownership of record materialization remain constraints.

## Responsibility and dependency map

| Owner | Decision | Output consumed elsewhere |
| --- | --- | --- |
| `compiler.source` | Parse Python and describe authored syntax and locations | Source facts; compiler-internal parsed syntax |
| `compiler.adaptation` | Interpret annotations, resolve aliases, materialize records, preserve authored typing contracts | Origin-bearing `StubModule`, including reusable semantic roots |
| Shared `semantics` | Meaning of Typeforge relationships and predicates | Existing semantic results; no source layout or overlay policy |
| `compiler.verification` (proposed home for verification analysis) | Derive return contracts and analyze recognized implementation flow | Checker-neutral return obligations |
| `compiler.specialization` | Produce finite generated interfaces | Specialized `StubModule` |
| `compiler.pipeline` | Order compiler work, preserve failure boundaries, assemble the plan | `CompilationPlan` |
| `compiler.module_surface` | Decide what a complete published interface can preserve | `ModuleSurface` or its existing typed failure |
| `overlay` | Select overlay typing fallbacks, emit checks and declarations, place edits, construct mappings | `VirtualDocument` |
| `diagnostics` | Explain checker results using authored descriptions and obligation provenance | User-facing explanations |

Compiler analysis must not import overlay, diagnostics, analysis document models,
or checker adapters. Verification moves behind the compiler seam, with source spans
owned by the compiler rather than importing `analysis.model.SourceSpan`.

## 1. Frontend seam: parse a source snapshot

Proposed compiler-internal interface:

```python
def parse_source(
    source: str,
    path: Path,
) -> Result[ParsedSource, SourceSyntaxError]: ...
```

`ParsedSource` is a compiler-internal parsing result, not another generated-module
stage. It keeps the original syntax tree available to compiler analyses alongside
Typeforge-owned source facts. Its exact private storage is not a public contract.
The public `CompilationPlan.source` receives the source facts, not this parsing
result or its AST.

Source facts needed at consumer seams:

- Exact authored text and path, so text slices and locations refer to one snapshot.
- Existing declarations, qualified names, annotation spelling, and type parameters.
- Declaration locations including decorator extents, while preserving the existing
  declaration spans used as origin identities.
- Module docstring and leading future-import extents.
- Statement, expression, and suite extents needed by emitted return checks.
- Identifier occurrence information needed for deterministic generated-name
  collision avoidance.

These are syntax facts. The frontend does not choose an overload insertion offset,
extra import names, indentation for generated code, or verification assignments.
Use a documented source-coordinate convention; conversions to editor/checker
coordinates belong to projection and integration code.

The parser must not read the supplied path or execute authored code. The path-based
entry point reads once before calling it. No consumer repairs missing source facts
by parsing or reading the file again.

## 2. Adaptation seam: produce IR and retain authored contracts

Retain the existing compositional interface:

```python
def adapt_source_module(
    source: SourceModule,
) -> Result[StubModule, AdaptationError | RecordMaterializationError]: ...
```

Adaptation remains responsible for annotation interpretation, alias expansion,
record materialization, and origin maintenance. Verification must not call
`adapt_function`, recollect aliases, or expand them independently.

There is an information requirement that the current interface must satisfy:
verification needs the interpreted authored callable signature before record
rewriting or finite specialization changes its meaning or reference form. For
example, it needs the declared relationship between parameter `value: T` and a
`Map` return type, not an attempt to infer that relationship from emitted overloads.

**Approved representation (implemented in slice 2):** generalize the existing reusable expression roots
to reusable generated elements. This uses the already-owned `GeneratedElement`
union and existing origins to retain an interpreted `FunctionDeclaration` as an
authored contract, alongside the reusable alias/schema expressions:

```python
# Replaces StubModule.expressions; no additional side table.
reusable_elements: tuple[GeneratedElement, ...]
```

Only retain a callable root when a current analysis needs that authored contract.
Its parameter and return types are adapted once by the existing annotation owner.
Record rewriting and specialization transform generated declarations while
preserving this declared contract. This is a current semantic value with a named
consumer, not a log of previous module snapshots.

An authored span can consequently identify both a reusable callable contract and
its generated overloads. The collection in which an element resides distinguishes
those roles. Origins must still target elements reachable in the current module;
no matching by unqualified name or reconstruction from emitted text is permitted.

This representation change was approved for slice 2 on 2026-09-06. An alternative considered was a
separate typed-callable catalog returned by adaptation. That makes the contract
collection explicit, but creates another carrier and association model alongside
IR origins. Generalizing the existing roots preserves the small stage interface
and keeps identity tracking in one place. Neither option justifies returning
record-materialization deltas to the pipeline.

## 3. Verification seam: analyze bodies against retained contracts

Proposed compiler-internal module interface:

```python
def analyze_implementations(
    parsed: ParsedSource,
    module: StubModule,
) -> VerificationPlan: ...
```

Inputs are the original parsed syntax and the adapted module containing reusable
authored contracts. This function owns callable/body association, return-contract
construction, recognized guards and control flow, and conservative degradation.
The AST is an input to compiler analysis, not an output exposed to overlay.

Within that module, the contract-building function becomes a typed-IR operation:

```python
def build_return_contract(
    signature: FunctionDeclaration,
) -> ReturnContract | None: ...
```

`FunctionDeclaration` here is stub IR, not an authored declaration that needs
adapting. Authored identity comes from its origin. `None` means the existing
verification rules do not apply, such as an ambiguous controller or an unsupported
relationship. It must not mean that a compiler error was swallowed.

Keep all current flow policies: generators and declaration-only bodies, recognized
and unknown guards, controller reassignment, loops, exceptions, explicit returns,
and implicit fallthrough. Do not infer ordinary Python expression types.

### Obligation data

Keep the existing `VerificationPlan` concept, but make its contents independent of
text-edit construction. Each obligation needs:

- The authored callable/contract reference.
- The controlling parameter identity needed for provenance.
- A return site: an explicit return statement and optional expression location, or
  an implicit return at the end of an authored suite.
- Expected types as compiler IR.
- Recognized narrowed inputs as compiler IR, where applicable.

Explicit return and implicit fallthrough are real semantic distinctions. A bare
`return` and an implicit return both have the value `None`, but different sites.
Represent that distinction deliberately rather than encoding it in newline flags.

Remove `insertion_offset`, `indentation`, `inline`, `starts_line`, and
`leading_newline` from compiler obligations. Preserve the source extents that allow
overlay to derive those decisions. Expression text comes from the retained source
snapshot; diagnostic type strings are rendered by their consumer.

No new verification error family is currently justified. Annotation failures
belong to adaptation. Unsupported flow retains its existing conservative outcome;
an empty obligation set is a valid complete result. Unexpected failures propagate.
If migration exposes an existing modeled verification-only failure that does not
fit this account, resolve its ownership before implementing its conversion.

## 4. Specialization seam: preserve the existing module contract

```python
def lower_variadic_module(
    module: StubModule,
    frontier: ArityFrontier,
) -> Result[StubModule, LoweringError]: ...
```

Specialization owns finite generated declarations and the associated origin
updates. Reusable authored contracts remain intact. Verification consumes those
contracts, so its result must not depend on the selected finite arity frontier.

No `AdaptedModule`, `SpecializedModule`, or pipeline-owned rewrite bookkeeping is
introduced.

## 5. Public compilation seam: return completed analysis

Keep the entry point:

```python
def compile_source(
    source: str,
    path: Path,
    maximum_arity: int,
) -> Result[CompilationPlan, CompilationError]: ...
```

Proposed plan shape:

```python
@dataclass(frozen=True, slots=True)
class CompilationPlan:
    source: SourceModule
    module: StubModule
    verification: VerificationPlan
```

`source` is enriched source data without an AST. `module` is specialized IR with
current origins and retained semantic roots. `verification` contains completed
checker-neutral obligations, not a callback or deferred instruction to reanalyze.

Required data dependencies are parse → adaptation → specialization and
parse + retained contracts → verification. Preserve the existing reported
adaptation/specialization failure order; verification need not run when those
stages fail. It may consume retained contracts after specialization, because those
roots remain unchanged. This avoids making execution order responsible for
recovering discarded information.

The pipeline only composes these operations. It does not derive return contracts,
walk AST nodes, choose edit positions, or match generated declarations by name.

A compilation failure returns no partial plan. A successful plan can have no
obligations. Existing `describe_authored_callables(plan)` remains a source-data
projection and performs no parsing or annotation interpretation.

## 6. Overlay seam: project a completed plan

Proposed independently testable projection:

```python
def project_overlay(
    plan: CompilationPlan,
    *,
    version: int = 0,
) -> Result[VirtualDocument, OverlayError]: ...
```

It has no separate source string or maximum arity: the source snapshot and finite
specialization are already fixed by the plan.

Existing `transform_source(source, path, maximum_arity, version)` remains the
convenience entry point. It owns the existing invalid-arity and generated-source
sentinel fast paths, calls `compile_source` once, then calls `project_overlay`.

Overlay owns:

- Its relationship union fallbacks and rendering policies.
- Emitting generated overloads, alias/schema edits, and derived records.
- Inserting overloads before authored decorators.
- Choosing import placement from docstring/future-import facts.
- Turning return obligations into typed assignments with collision-free names.
- Handling inline suites, semicolons, whitespace, comments, and end-of-file layout.
- Constructing source mappings and return-check provenance.

It does not import `ast`, call verification analysis, adapt annotations, expand
aliases, specialize types, or recover facts from source syntax. String slicing and
line/offset calculations against retained source text remain legitimate projection
work.

Emission failures remain projection failures. Preserve the existing policy for a
verification obligation whose expected type cannot be emitted; do not silently
replace it with a new compiler-wide failure policy during this migration.

## 7. Publication and diagnostics seams

`generate_module(path, maximum_arity)` remains the path-based publication entry.
Its publication surface analysis should consume the same compiler-internal parsed
snapshot:

```python
def inspect_module_surface(
    parsed: ParsedSource,
) -> Result[ModuleSurface, UnsupportedPublicDeclaration]: ...
```

It must not reread/reparse the file independently, as the current implementation
does. Publication owns complete-interface validation and assembly. Its existing
surface-error priority and historical source-scope policy must be preserved; it
may validate the parsed surface before invoking the shared compilation core.
Do not implement publication simply as “compile everything, then validate” where
that reverses an existing failure contract.

Published stub emission does not emit implementation obligations. Moving analysis
behind the compiler must not make valid published interfaces depend on overlay
formatting or checker instrumentation.

Diagnostics keep their current presentation interface over retained callable
metadata and provenance. Compiler verification stores typed facts; overlay records
which generated check corresponds to which obligation; diagnostics decide wording.
The compiler must not depend on diagnostic models or rendered messages.

## Observable contract and tracer proposal

Proposed first tracer: an authored generic function with a `Map` return annotation,
a recognized `type(value) is int` branch, and a return expression in that branch.

Through `compile_source`, assert that:

1. The plan retains the exact authored source snapshot.
2. Its obligation identifies that return expression and expects the selected
   branch's output type.
3. The obligation contains no generated assignment or text-placement instructions.

Through `project_overlay`, assert that:

4. The existing expected assignment text and source mapping are produced.
5. Projection succeeds after parsing and compiler-analysis entry points are disabled.

Count full authored-module parses at the entry point: exactly one, and zero for
projection of an existing plan. Do not confuse parsing a generated test result or
an isolated compiler-internal expression with reparsing the authored module.

Further contracts before declaring the migration complete:

- Decorated async methods and same-named methods in nested/conditional scopes.
- Module docstrings and future imports, including multiline forms.
- Inline returns, semicolon-separated statements, bare returns, fallthrough,
  comments, and missing final newlines.
- Unicode source locations and deterministic generated-name collision handling.
- Unknown guards, reassigned controllers, generators, and ambiguous controllers
  preserve current conservative behavior.
- Relationship aliases and record rewriting preserve the authored contract used
  for verification; changing maximum arity does not change obligations.
- Syntax, adaptation, record, specialization, surface, and emission failures retain
  their intended owner, short-circuiting, and presentation.
- Sentinel/invalid-arity paths remain compilation-free.
- Architecture rules forbid AST dependencies and compiler stage calls in overlay
  and diagnostics, and forbid compiler dependencies on target/checker modules.

## Implementation slices

These are tracked work items; completion evidence is recorded beneath each title.
The representation choices for slices 1–2 are approved. Preserve the existing
workflow: one implementation agent per slice, followed by independent primary
review. Do not run dependent slices concurrently.

Implement and validate one observable contract at a time. Each slice must leave
the repository coherent and include its own regression tests; slice 6 does not
defer testing of earlier behavior. Prefer changes below 400 substantive lines per
review increment. If a slice exceeds that target, split its review into coherent
increments and report the reason and actual size. Report pure file relocations
separately from substantive additions/deletions.

Cross out only the completed slice title, for example:
`1. ~~Parse once and retain source facts~~ — completed YYYY-MM-DD (N changed lines)`.
Record exact validation commands and outcomes beneath it. A slice is complete only
after its contracts pass normally, any strict xfails for that capability are
removed, focused and full `make check` pass, and independent review finds no
unrelated changes. Do not cross out partial slices or mark a planned test as passing.

1. ~~Parse once and retain source facts~~ — completed 2026-09-06 (385 changed lines)

   Delivered `ParsedSource(source, tree)` for compiler-internal use; public facts
   retain exact text/path, callable decorator and suite spans, preamble spans,
   lexically ordered return sites, and name/parameter occurrences. Existing
   parser callers now select `.source` explicitly. Original declaration origins
   and syntax-error offsets remain unchanged.

   Four ordinary passing contracts in `test_source_snapshot.py` cover one parse,
   no path read/execution, exact source identity, multiline/nested/Unicode sites,
   unused nested/lambda parameter names, and recursive AST exclusion from plans.
   The initial red exposed missing source text; the additional identifier red
   exposed missing parameter declarations. No xfails were added.

   Validation: `make check src/typeforge/compiler/source src/typeforge/compiler/pipeline tests/unit/compiler/source tests/unit/compiler/pipeline tests/unit/compiler/adaptation tests/unit/compiler/record_materialization tests/unit/compiler/specialization tests/unit/compiler/module_surface`
   and independent `make check` both passed all six checks. Primary review also
   replayed 89 baseline overlay cases with identical generated text, mappings,
   callable metadata, and failures; `git diff --check` passed. Size is 321 additions
   plus 64 deletions across 14 source/test files, including caller migration;
   no relocations. Overlay/publication reparsing remains for later slices.

   Establish the compiler-internal parsed-source seam and retain exact authored
   text, declaration/decorator extents, preamble facts, relevant source-site
   extents, and identifier information. Carry public facts into the compilation
   plan without exposing its AST. Keep existing compiler consumers working while
   consumer parsing is removed in later slices.

   Complete when frontend/pipeline contracts show one parse for compilation, exact
   source identity and locations, no source-path read or execution, and no AST in
   the public plan. Cover multiline decorators/docstrings/future imports, nested
   scopes, and Unicode coordinates through readable authored examples. This slice
   does not claim that the existing overlay or publication paths are already
   reduced to one parse.

   Owners: `compiler.source`, `compiler.pipeline`. Tests: source parser/model and
   pipeline contracts. Prerequisite: agree the parsed-source/public-facts split and
   coordinate convention.

2. ~~Preserve reusable callable contracts~~ — completed 2026-09-06 (315 changed lines)

   Replaced `StubModule.expressions` with `reusable_elements` and migrated all
   callers. Adaptation retains expanded Map callable signatures before record
   rewriting; materialization and specialization preserve those roots by identity.
   Existing origins associate authored spans with retained contracts and generated
   overloads. Traversal visits declaration roots and their nested types; overlay
   schema edits explicitly select type roots. Roots do not emit extra declarations
   or imports. No parallel catalog or compatibility field was introduced.

   Ordinary passing contracts in `test_callable_contracts.py` cover direct/aliased
   record outputs, two arity frontiers, ordinary-function exclusion, same-named
   class/conditional callables, enclosing type variables, origin identity/order,
   and predicate/schema reachability. Existing traversal, emission, alias, and
   schema tests were extended or migrated. The initial red exposed the missing
   `reusable_elements` field; no xfails were added or removed. The Map example's
   overload count is independent of arity; mixed Map/Each support was not added.

   Validation: `make check src/typeforge/compiler/adaptation src/typeforge/compiler/stub_ir src/typeforge/compiler/specialization src/typeforge/compiler/emission src/typeforge/compiler/pipeline src/typeforge/overlay tests/unit/compiler/adaptation tests/unit/compiler/stub_ir tests/unit/compiler/specialization tests/unit/compiler/emission tests/unit/compiler/pipeline tests/unit/overlay`
   and independent `make check` both passed all six checks. Primary review replayed
   the same 89 overlay cases with exact output/mapping/metadata/failure parity.
   Retained signatures also match 49 callables from the previous verification
   adaptation path across 79 successful compilations. `git diff --check` passed;
   no old field callers remain in source/tests. Size is 276 additions plus 39
   deletions across 13 files, with no relocations.

   Combined slices 1–2: 700 source/test changed lines across 25 files, excluding
   task documentation. Both slices received independent primary review. Stop here
   for user review; verification ownership and consumer parsing remain for slices
   3–6.

   Implement the reviewed reusable-root representation. Retain interpreted
   callable signatures at adaptation, before record rewriting or specialization
   loses the declared relationship. Use existing origins to associate contracts
   with authored callables. Preserve alias/schema root behavior and materialization
   ownership; do not introduce a parallel compilation path.

   Complete when a callable's interpreted parameter/return relationship remains
   available through record materialization and finite specialization, ordinary
   declarations remain correctly excluded, and all origin targets are current and
   deterministically ordered. Existing alias/schema output and emission contracts
   must remain unchanged.

   Owners: adaptation, stub IR, specialization. Tests: adaptation/specialization
   origins, IR traversal, emission, alias/schema overlays. Depends on the approved
   contract representation; follow slice 1 in the implementation sequence.

3. **Separate verification analysis from overlay formatting** — planned
   (300–450 substantive changed lines, plus code relocation)

   Move contract and flow analysis behind `compiler.verification`. Consume retained
   typed signatures and the original parsed bodies; remove independent annotation
   adaptation and alias expansion. Define checker-neutral obligations with explicit
   return/fallthrough sites and typed expected/narrowed inputs. Move indentation,
   semicolon, newline, and insertion policy into overlay projection.

   Complete when compiler analysis produces the same supported obligations without
   importing target document/diagnostic models or storing edit-formatting flags.
   Preserve current conservative behavior for unknown guards, controller mutation,
   generators, exceptions, loops, and ambiguous controllers. Keep the existing
   overlay runnable during the move; migrate callers instead of copying the flow
   algorithm. Any temporary compatibility entry must name its caller and be removed
   by slice 4.

   Owners: compiler verification and overlay. Tests: focused compiler obligations
   and the existing implementation-verification/diagnostic regressions. Depends on
   slices 1–2 and agreement on return-site data.

4. **Assemble completed plans and project overlays** — planned (200–350 changed lines)

   Add completed verification data to `CompilationPlan`; compose analysis behind
   `compile_source`. Introduce `project_overlay(plan, version=...)` and make
   `transform_source` compose compilation and projection after its existing fast
   paths. Delete overlay's second module parse, duplicate callable walk, and calls
   into verification analysis. Use source facts for insertion and import placement.

   Complete the end-to-end tracer described above: inspect the obligation through
   `compile_source`, then obtain exact generated text and mappings through
   `project_overlay` with parsing and compiler analysis disabled. Count one authored
   module parse for transformation, zero for projection, and zero for the sentinel
   and invalid-arity fast paths. Preserve diagnostics and failure short-circuiting.

   Owners: pipeline and overlay; adapter/proxy integration only as required by the
   transported data. Tests: pipeline, overlay, implementation verification, and
   diagnostics. Depends on slices 1–3.

5. **Make publication reuse the parsed source** — planned (100–200 changed lines)

   Change module-surface inspection and its import/variable helpers to consume the
   original compiler-internal parsed snapshot. Remove repeated file reads and
   module parses. Keep publication's source-scope policy, surface-validation
   priority, and final assembly distinct from shared compiler analysis.

   Complete when path-based generation reads and parses authored source once,
   preserves exact published fixtures, retains syntax → surface → compiler failure
   priority, and emits no implementation-check instrumentation. Include the existing
   ignored-scope and opaque TypedDict annotation regressions.

   Owners: compiler source, module surface, pipeline generation. Tests: module
   surface and published pipeline. Depends on slice 1; it can be scheduled after
   the core overlay cutover without changing slices 2–4.

6. **Enforce boundaries and finish cleanup** — planned (100–200 changed lines)

   Extend the shared architecture topology and tests to prevent AST access and
   compiler-stage reconstruction in overlay/diagnostics, and compiler dependencies
   on target/checker modules. Remove the superseded external verification package,
   dead helpers, and compatibility exports once their callers have migrated. Keep
   shared typing operations with their existing appropriate owner.

   Complete when architecture rules and full repository checks pass, no stale
   migration xfails or duplicate semantic paths remain, and all consumers use the
   intended seams. Review exact output/mapping/failure regressions across both
   targets; update public/developer documentation for changed interfaces. Record
   final scope, substantive size versus moves, and any retained helper's concrete
   consumer. Then mark this task complete.

   Owners: affected package interfaces, architecture tests, documentation. Depends
   on slices 1–5; no feature logic should be postponed to this cleanup slice.

## Size and validation plan

Planning estimate: approximately 1,200–2,000 substantive changed lines including
tests, across roughly 25–35 files. About 1,100 existing verification lines may be
relocated. A raw diff counting moves as deletion plus addition could total roughly
3,000–4,000 lines. These are medium-confidence estimates, not implementation caps;
return-site data and contract retention are the main uncertainties.

Run focused checks on each slice's owning source and test paths, then `make check`.
For the final combined scope, the broad focused command is:

```console
make check src/typeforge/compiler src/typeforge/overlay src/typeforge/diagnostics src/typeforge/analysis src/typeforge/adapters src/typeforge/proxy tests/unit/compiler tests/unit/overlay tests/unit/verification tests/unit/diagnostics tests/unit/adapters tests/unit/proxy tests/architecture
make check
```

Adjust paths if tests move with their owner. Full checks include pytest, Ruff lint
and formatting, Flake8 block spacing, mypy, and pyright. Do not change dependencies
or `uv.lock` unless the approved work actually requires them.

Useful existing regression entry points:

- [Compilation and origins](../../tests/unit/compiler/pipeline/test_compilation.py)
- [Published failure priority](../../tests/unit/compiler/pipeline/test_published_plan.py)
- [Module surface](../../tests/unit/compiler/module_surface/test_module_surface.py)
- [Overload/alias projection and fast paths](../../tests/unit/overlay/test_compilation_plan.py)
- [Schema boundaries and opaque publication fields](../../tests/unit/overlay/test_schema_plan.py)
- [Implementation verification](../../tests/unit/verification/test_implementation_verification.py)
- [Authored diagnostic presentation](../../tests/unit/diagnostics/test_diagnostic_presentation.py)
- [Compiler consumer architecture](../../tests/architecture/test_compiler_consumers.py)

These are baseline tests, not evidence that the new proposed contracts already
exist. Keep new tests readable with dedented authored programs, named scenario
cases, explicit expected types/text/spans, and keyword arguments for metadata.

## Review ledger and handoff boundary

Accepted direction: verification analysis belongs behind the compiler seam;
overlay projects completed compiler results; authored source is parsed once.

Approved direction (2026-09-06); implementation is authorized for slices 1–2:

1. Generalize reusable roots to include interpreted callable contracts, keeping
   adaptation's `StubModule` return rather than introducing a parallel catalog.
2. Add completed `verification` data to `CompilationPlan` and retain exact source
   text with its authored source facts.
3. Add a plan-only `project_overlay` interface beneath `transform_source`.
4. Keep parsed AST access compiler-internal, including publication surface analysis.

Names of new source-site records are deliberately not frozen yet. Their required
information and owners are specified above; no generic Python AST replacement,
service classes, speculative protocols, or extra configuration switches are planned.

The implementation handoff is to complete slices 1–2, then stop for user review.
Each slice starts with an executable failing contract and leaves it as an ordinary
passing regression. Later slices remain planned. Relevant validation will cover
compiler source/adaptation/specialization/pipeline/verification, module surface,
overlay, diagnostics, architecture tests, and full `make check`.
