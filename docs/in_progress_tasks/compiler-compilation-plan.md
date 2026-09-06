# Compiler Compilation Plan

Status: In progress — external seam and simplified `StubModule` stage composition
agreed; prerequisites and first seven implementation slices complete

## Outcome

The compiler retains a target-neutral object representation of one module
compilation. The representation lets stub generation, overlay generation, and
diagnostic presentation consume the same compiler decisions without
rediscovering them from authored source.

Success is observable when:

- the compiler associates a generated overload with the authored function that
  caused it;
- the overlay no longer imports `contains_marker()` to decide which authored
  declarations require Typeforge output;
- diagnostics no longer imports `enriched_functions()` or reparses authored
  source to recover callable information; and
- published stub text, overlay text and mappings, diagnostic presentation, and
  modeled failures remain unchanged.

## System and ownership

`typeforge.compiler.pipeline` owns compilation planning and its public
interface. It composes authored source into immutable `StubModule` snapshots
without adding stage-specific module types or declaration-specific
transformation models.

`compiler.source` owns authored Python data, parsing, marker normalization, and
source-expression queries. `compiler.stub_ir` owns target-neutral generated
typing data, including the closed `GeneratedElement` union, its origin
association, and `StubModule.origins`.

`SourceSpan` is the only authored-source model stored in stub IR. Stub IR does
not contain authored declarations or authored type-expression trees.

Stub generation and overlay generation are target-specific projections of a
compilation plan. Diagnostics consume authored information preserved by the
plan rather than running compiler source queries independently.

## Language

- **Compilation plan**: the target-neutral result of compiling authored source
  into specialized compiler IR before complete-stub surface assembly or text
  emission.
- **Compilation provenance**: the current
  `GeneratedElementOrigin[SourceSpan]` associations stored in
  `StubModule.origins`.
- **Generated element**: an existing stub-IR declaration or type expression.
- **Stub module snapshot**: one immutable, internally consistent state of stub
  IR and the origins of its generated elements.
- **Target projection**: conversion of a compilation plan into published stub
  output or an in-memory overlay.

Origins describe the current stub module. They are not an execution trace of
adaptation, record materialization, specialization, or emission.

## Approved external seam

The public seam is `typeforge.compiler.pipeline.compile_source()`:

```python
def compile_source(
    source: str,
    path: Path,
    maximum_arity: int,
) -> Result[CompilationPlan, CompilationError]: ...
```

`typeforge.compiler.stub_ir` owns the generated-element union and origin
association:

```python
type GeneratedElement = Declaration | StubTypeExpression


@dataclass(frozen=True, slots=True)
class GeneratedElementOrigin[OriginType]:
    origin: OriginType
    generated: GeneratedElement
```

Origins live on the module containing the generated elements:

```python
@dataclass(frozen=True, slots=True)
class StubModule:
    name: str
    declarations: tuple[Declaration, ...]
    imports: tuple[ModuleImport, ...] = ()
    origins: tuple[GeneratedElementOrigin[SourceSpan], ...] = ()
```

The compilation plan does not duplicate those origins:

```python
@dataclass(frozen=True, slots=True)
class CompilationPlan:
    source: SourceModule
    module: StubModule
```

`CompilationError` contains only modeled failures possible before target
surface assembly and emission: source syntax, adaptation, specialization, and
record materialization failures. No partial plan crosses the seam after one of
these failures.

`generate_module()` remains the path-based interface for complete published
stubs. It may add the inspected module surface and perform emission after
compilation. The in-memory overlay must remain able to accept runtime statements
that complete-stub surface validation does not support.

## Agreed compositional stage seams

These seams are encoded as strict-xfail contracts. Record materialization is
part of adaptation rather than a pipeline-visible stage.

Adaptation creates the complete initial target-neutral `StubModule`. It adapts
authored declarations, materializes record declarations, applies record-driven
replacements, and records authored origins for Typeforge-generated elements:

```python
def adapt_source_module(
    source: SourceModule,
) -> Result[
    StubModule,
    AdaptationError | RecordMaterializationError,
]: ...
```

Finite specialization also consumes and returns `StubModule`. When it replaces
a function with generated overloads, the returned origin points directly from
the authored `SourceSpan` to the resulting `OverloadDeclaration`:

```python
def lower_variadic_module(
    module: StubModule,
    frontier: ArityFrontier,
) -> Result[StubModule, LoweringError]: ...
```

The stages therefore compose without pipeline-owned origin bookkeeping:

```text
SourceModule
    -> StubModule
    -> StubModule
    -> CompilationPlan
```

Adaptation and specialization each own the origin changes caused by their
transformations. The pipeline does not receive record-materialization plans,
`introduced` or `rewritten` deltas, advance rewrite edges, match declarations
by name, or diff independently produced modules.

The existing `RecordMaterialization` data remains an internal implementation
detail of record discovery and evaluation behind `adapt_source_module()`. It is
not a pipeline seam, and no public `materialize_records()` stage is added.

Adaptation must preserve target-neutral relationship IR such as `MapType`.
Published-stub projection retains the existing conservative `object` fallback,
while overlay projection retains its existing union-of-outputs fallback. Neither
fallback is selected during adaptation.

## Rules and invariants

1. `compile_source()` parses the supplied text. It does not read, import, or
   execute the authored module at `path`.
2. `CompilationPlan.source` is the parsed `SourceModule` for the supplied text
   and path.
3. `CompilationPlan.module` is specialized compiler IR for `maximum_arity`. It
   is neither final `.pyi` text nor generated overlay text.
4. `StubModule` is an immutable snapshot. A successful stage returns a complete
   new snapshot; a failed stage leaves its input unchanged and returns its
   modeled failure.
5. Every entry in `StubModule.origins` refers to a generated element present in
   that same snapshot. Replaced or removed elements cannot retain stale origin
   entries.
6. Origins contain Typeforge-generated associations. An ordinary declaration
   can appear in `declarations` without an origin entry.
7. Each origin uses an authored span from the compilation source path and an
   immutable stub-IR value.
8. One authored span can have multiple origin entries. Several authored spans
   can point to equal generated values. This represents one-to-many and
   many-to-one relationships without transformation variants.
9. Origin ordering is deterministic: authored source position first, then
   generated declaration order for entries with the same authored position.
10. Stub IR owns the closed `GeneratedElement` union so pattern matching and
    static checking expose unhandled generated-element categories when the IR
    is extended.
11. Target projections preserve current generated text, source mapping,
    failure, and diagnostic behavior.
12. Modules outside the compiler consume compilation through
    `compiler.pipeline`; they do not import compiler source queries or
    individual compiler stages to reconstruct the plan.

Creating the next immutable snapshot does not mean reparsing source or cloning
the complete IR tree. Unchanged immutable declarations and type expressions may
be shared between snapshots. No public mutation or module-update operation is
part of the seam.

## Tracer contract

System under definition: module compilation planning.

Owning module: `typeforge.compiler.pipeline`.

Rule: a function that causes finite overload generation is associated with its
generated `OverloadDeclaration` through `CompilationPlan.module.origins`.

Given authored source with an ordinary generic function followed by an
`Each`/`Collect` function, when `compile_source()` compiles it with maximum arity
one, then:

- the plan retains both authored functions;
- the plan's compiler IR contains the generated overload declaration;
- exactly one module origin associates the enriched function span with that
  overload; and
- the ordinary function has no origin entry.

The missing capability is that the current pipeline immediately emits a
`GeneratedModule` and does not return a compilation plan with origin-bearing
stub IR.

Executable contract:
[`tests/unit/compiler/pipeline/test_compilation.py`](../../tests/unit/compiler/pipeline/test_compilation.py)

Internal seam review contracts:

- [`tests/unit/compiler/adaptation/test_adaptation_origins.py`](../../tests/unit/compiler/adaptation/test_adaptation_origins.py)
- [`tests/unit/compiler/specialization/test_specialization_origins.py`](../../tests/unit/compiler/specialization/test_specialization_origins.py)

## Implementation slices

Each feature slice should remain below 400 changed lines and leave the repository in
a coherent state. Complete the slices in order unless a dependency has already landed.

Cross out a slice only when its contract passes normally, any strict `xfail` for that
capability has been removed, and the focused checks pass. Record completion as, for
example, `1. ~~Core callable tracer~~ — completed 2026-09-04`. Do not cross out
partially completed slices.

### Prerequisite (not a feature slice)

~~Reconcile the existing `TypeParameter.span` mismatch between the source model and
parser.~~ — completed 2026-09-04

~~Preserve unchanged type-expression identity in shared traversal for schema-origin
tracking.~~ — completed 2026-09-05 (45 changed lines)

1. ~~Core callable tracer~~ — completed 2026-09-04 (approximately 200–300 changed lines)

   Attach origins to top-level enriched functions during adaptation, carry those
   origins onto generated overloads during specialization, and implement the
   `compile_source` orchestration shell. Complete this slice when the specialization
   and pipeline strict-`xfail` contracts pass normally.

2. ~~Target-neutral aliases~~ — completed 2026-09-04 (approximately 150–250 changed lines)

   Preserve `MapType` in the compiler IR, attach the authored alias origin, and move
   the conservative `object` fallback into published-stub projection. Complete this
   slice when the target-neutral alias adaptation contract passes normally and the
   existing published output remains unchanged.

3. ~~Records become part of adaptation~~ — completed 2026-09-05 (269 changed lines)

   Move existing record discovery behind `adapt_source_module`, include materialized
   records and their origins in its returned `StubModule`, remove separate record
   orchestration from the pipeline, and preserve `RecordMaterializationError` at the
   compiler boundary. Complete this slice when the record-origin adaptation contract
   passes normally.

4. ~~Enriched method origins~~ — completed 2026-09-05 (117 changed lines)

   Extend class lowering so overloads generated for enriched methods retain the
   authored method origin. Complete this slice when `compile_source` associates a
   nested generated overload with its authored method declaration.

5. ~~Nested schema origins~~ — completed 2026-09-05 (1,170 changed lines, including
   the 45-line traversal prerequisite)

   Attach origins to generated type expressions produced from `Schema`, including
   nested and repeated uses, without introducing pipeline-owned element variants.
   Complete this slice when schema-origin ordering and association are deterministic.

   Reviewed in two increments: expression origins through adaptation and record
   rewrites, then propagation through finite specialization. The original 400-line
   review target was exceeded: exact identity tracking required explicit rewrite
   notifications through existing recursive operations, plus regressions for nested
   unions, repeated uses, alias copies, overloads, and fallbacks. Pipeline interfaces
   and generated-text behavior remain unchanged; full `make check` passes.

6. ~~Derived-record provenance~~ — completed 2026-09-05 (101 changed lines)

   Allow a derived record to identify multiple authored causes using the existing
   `GeneratedElementOrigin` representation, without introducing record-specific
   origin variants. Complete this slice when shared records have all and only their
   current authored causes.

   Each derived record retains its transform alias and input TypedDict declaration
   as direct authored causes. Shared consumers retain their own overload origins.
   Exact identity and ordering contracts pass normally; focused and full
   `make check` pass.

7. ~~Published generation consumes the plan~~ — completed 2026-09-05 (200 changed lines)

   Route published-stub generation through `CompilationPlan`, keeping target-specific
   module shaping in projection and preserving generated text and modeled failures.
   Complete this slice when duplicate published pipeline choreography has been
   removed.

   Both entry points share parsed-source compilation into `CompilationPlan`.
   Published projection consumes that plan, preserving surface-validation priority
   and existing fixture output. Seven new contracts and all 55 pipeline tests pass;
   focused and full `make check` pass.

8. **Overlay overloads consume the plan** (approximately 250–350 changed lines)

   Make overlay transformation obtain generated overloads from `CompilationPlan`
   while preserving rendering, insertion locations, and source mappings. Complete
   this slice when the overlay no longer independently compiles enriched functions.

9. **Overlay aliases consume the plan** (approximately 180–300 changed lines)

   Render alias replacements from the plan, apply the overlay-specific union fallback
   during projection, and remove the overlay dependency on `contains_marker`.
   Complete this slice when alias output remains unchanged through the common seam.

10. **Overlay schemas and records consume the plan** (approximately 250–350 changed lines)

    Render schema replacements and records from plan IR plus origins, remove direct
    record-helper imports from overlay, and preserve output and source mappings.
    Complete this slice when all remaining overlay generation uses the common seam.

11. **Diagnostics and architecture enforcement** (approximately 250–350 changed lines)

    Carry authored callable descriptions through the compiler seam, update diagnostics
    to consume them instead of reparsing through `enriched_functions`, and add
    architecture tests preventing overlay and diagnostics from importing
    `compiler.source` helpers directly. Resolve the final ownership of callable
    descriptions within this slice. Complete it when obsolete exports are removed and
    the architecture checks pass.

## Counterexamples and edge cases

- An ordinary function belongs to compiler IR but does not receive an origin.
- A synthetic `StubModule` used only for emission can have empty origins.
- A failed transformation does not mutate its input module or return a partial
  module.
- An overlay can contain runtime statements that are unsupported in a complete
  published stub. Compilation planning must not perform target-specific module
  surface validation.
- Published stubs and overlays can render the same relationship differently.
  The plan therefore must not store either target's final text as the common
  representation.
- Syntax and modeled compiler failures return `Failure`; they do not produce an
  empty or partial plan.

## Non-goals

- Do not change Typeforge marker or schema semantics.
- Do not change generated stub or overlay output.
- Do not add `AdaptedModule`, `MaterializedModule`, `SpecializedModule`, or other
  stage-specific wrappers around `StubModule`.
- Do not expose record materialization as a pipeline-visible stage;
  `adapt_source_module()` owns complete initial stub IR construction.
- Do not expose introduced-element deltas, rewrite edges, or a general origin
  composition operation through compiler interfaces.
- Do not add callable-, alias-, schema-, or record-specific transformation
  variants unless a later accepted contract proves the generic origin model
  insufficient.
- Do not make `StubModule` mutable.
- Do not add authored declarations or authored type-expression trees to stub
  IR; `SourceSpan` origin metadata is the deliberate exception.
- Do not redesign implementation verification.
- Do not make project-local overlay output publishable.
- Do not introduce a protocol or adapter for this in-process seam.

## Assumptions and open questions

No material question remains about stage composition. Feature implementation
begins only after an explicit implementation handoff.

The transport used to carry diagnostic information from an overlay remains a
later non-blocking implementation choice constrained by the rules above.
