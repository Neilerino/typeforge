# Compiler analysis: proposed functional seams

Status: Draft for design review, 2026-09-06. No implementation, interface scaffolding,
or executable contract changes are authorized by this document.

This develops the responsibility split discussed after the
[compilation-plan migration](compiler-compilation-plan.md). That migration removed
most consumer compilation choreography, but overlay still parses authored source,
and verification still adapts annotations again. Those are remaining design gaps.

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

**Recommended representation:** generalize the existing reusable expression roots
to reusable generated elements. This uses the already-owned `GeneratedElement`
union and existing origins to retain an interpreted `FunctionDeclaration` as an
authored contract, alongside the reusable alias/schema expressions:

```python
# Proposed replacement for StubModule.expressions, not an additional side table.
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

This representation change is a proposal requiring review. An alternative is a
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

## Review ledger and handoff boundary

Accepted direction: verification analysis belongs behind the compiler seam;
overlay projects completed compiler results; authored source is parsed once.

Proposals requiring seam review:

1. Generalize reusable roots to include interpreted callable contracts, keeping
   adaptation's `StubModule` return rather than introducing a parallel catalog.
2. Add completed `verification` data to `CompilationPlan` and retain exact source
   text with its authored source facts.
3. Add a plan-only `project_overlay` interface beneath `transform_source`.
4. Keep parsed AST access compiler-internal, including publication surface analysis.

Names of new source-site records are deliberately not frozen yet. Their required
information and owners are specified above; no generic Python AST replacement,
service classes, speculative protocols, or extra configuration switches are planned.

This document is a design proposal. After explicit approval of these seams and the
tracer, the next specification step is one executable pending contract. Implementation
starts only after a separate implementation handoff. Relevant validation will cover
compiler source/adaptation/specialization/pipeline/verification, module surface,
overlay, diagnostics, architecture tests, and full `make check`.
