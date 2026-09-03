# Compiler Module Reorganization

Status: Proposed
Related task: `docs/in_progress_tasks/deferred-input-map-semantics.md`

## Goal

Reorganize `typeforge.compiler` into cohesive packages with explicit ownership and
dependency seams before resuming the compiler-to-semantics pipeline cutover.

This is primarily a structural refactor. Move existing data and behavior to their
owning domains, preserve generated output and downstream interfaces, and avoid
redesigning compiler algorithms as part of the move.

## Motivation

The compiler currently has source data, stub IR, semantic adapter data, pipeline
results, and stage behavior spread across files at the same package level. Names
such as `model.py`, `records.py`, `_pipeline_models.py`, and `_pipeline_utils.py`
do not communicate ownership, and several lateral imports exist only because a
helper or data type lives in the wrong file.

A package-first structure should make these distinctions explicit:

- authored Python source versus generated-stub IR;
- source adaptation versus finite specialization;
- compiler-owned semantic adaptation versus shared semantic meaning;
- record materialization versus general source adaptation;
- module-surface preservation versus pipeline orchestration;
- public package interfaces versus private implementation files.

## Non-goals

- Do not resume the schema pipeline cutover in this task.
- Do not restore the implementation from experimental commit `49356b9`.
- Do not change generated stub behavior.
- Do not redesign semantic evaluation, structural matching, alias expansion, or
  unresolved-type behavior.
- Do not introduce protocols for pure in-process transformations.
- Do not retain new compatibility shims except where an existing downstream
  compiler interface requires one.

## Target structure

```text
src/typeforge/compiler/
├── __init__.py
├── config.py
│
├── source/
│   ├── __init__.py
│   ├── _model.py
│   ├── _parser.py
│   └── _markers.py
│
├── stub_ir/
│   ├── __init__.py
│   ├── _model.py
│   ├── _tree.py
│   └── _imports.py
│
├── adaptation/
│   ├── __init__.py
│   ├── _models.py
│   ├── _source_to_ir.py
│   ├── _imports.py
│   └── _legacy_schema.py
│
├── semantic_adapter/
│   ├── __init__.py
│   ├── _types.py
│   ├── _lowering.py
│   └── _type_system.py
│
├── specialization/
│   ├── __init__.py
│   ├── _models.py
│   └── _lowering.py
│
├── record_materialization/
│   ├── __init__.py
│   ├── _models.py
│   └── _materialization.py
│
├── module_surface/
│   ├── __init__.py
│   ├── _models.py
│   └── _inspection.py
│
├── emission/
│   ├── __init__.py
│   └── _python.py
│
└── pipeline/
    ├── __init__.py
    ├── _models.py
    └── _generation.py
```

Private filenames have a local meaning in this structure: they are implementation
files behind the owning package's `__init__.py` interface. Cross-package callers
use package interfaces rather than importing these files directly.

## Domain ownership

### Authored source

`compiler.source` owns authored Python data and its parsing rules:

- source positions and spans;
- authored declarations and type expressions;
- AST parsing;
- marker normalization and validation;
- source-expression queries;
- extraction of the inner expression from a valid `Schema` boundary.

It does not know about stub IR, semantic evaluation, or generation.

Current homes:

```text
model.py       -> source/_model.py
frontend.py    -> source/_parser.py
_markers.py    -> source/_markers.py
```

### Stub IR

`compiler.stub_ir` owns the standard-typing representation used to construct a
stub:

- type-expression and declaration dataclasses;
- `StubModule`;
- exhaustive traversal and rewriting;
- type-variable substitution;
- import normalization.

It is a compiler leaf and does not depend on authored source or shared semantics.

Current homes:

```text
lowering.py data definitions -> stub_ir/_model.py
_type_tree.py                 -> stub_ir/_tree.py
substitute_type()             -> stub_ir/_tree.py
merge_imports()               -> stub_ir/_imports.py
```

### Source adaptation

`compiler.adaptation` translates authored source into stub IR. It owns ordinary
annotation adaptation, declaration adaptation, callable relationship aliases,
and the errors and data produced by those operations.

The existing compiler-owned schema resolver is moved without redesign to
`_legacy_schema.py`. This quarantines the duplicate matcher and possible-output
calculation so the final semantic cutover can delete that file rather than
untangling it from general adaptation again.

Current homes:

```text
_pipeline_adaptation.py -> adaptation/_source_to_ir.py
schema resolution path  -> adaptation/_legacy_schema.py
AdaptationError and
SemanticRelationshipAlias -> adaptation/_models.py
adaptation import analysis -> adaptation/_imports.py
```

### Compiler semantic adapter

`compiler.semantic_adapter` owns compiler-specific participation in the shared
`typeforge.semantics` interfaces:

- the compiler `StaticType` representation;
- lowering authored expressions into shared semantic expressions;
- `CompilerTypeSystem`;
- the future complete schema evaluation adapter.

The package is named `semantic_adapter` rather than `semantics` to distinguish it
from the shared `typeforge.semantics` package.

Current homes:

```text
records.py             -> semantic_adapter/_types.py
_semantic_lowering.py  -> semantic_adapter/_lowering.py
_type_system.py        -> semantic_adapter/_type_system.py
```

Future semantic-cutover slices may add `_aliases.py` and `_schema.py`, but this
reorganization does not create empty placeholder modules for them.

### Finite specialization

`compiler.specialization` owns deterministic `StubModule -> StubModule`
transformations over configured finite frontiers:

- `Each` and `Collect` specialization;
- callable `Map` overload lowering;
- `ArityFrontier`;
- `LoweringError`.

The behavior currently following the IR definitions in `lowering.py` moves here.
The name distinguishes finite specialization from source-to-IR and semantic
lowering.

### Record materialization

`compiler.record_materialization` owns compiler record discovery and generated
record declarations:

- building record shapes from authored `TypedDict` declarations;
- evaluating `MapFields` transforms;
- derived-record naming and specialization;
- converting materialized records into stub IR;
- record rendering needed by downstream overlay consumers.

`DerivedRecord` and `RecordMaterialization` move into this package. The package
must not depend on source adaptation. The current reused `AdaptationError` should
be replaced by a package-owned modeled error and converted at the existing outer
compiler boundary without changing public generated-module behavior.

### Module surface

`compiler.module_surface` owns preservation of the authored module's complete
public interface:

- validation of supported public declarations;
- module-variable discovery;
- public imports and other surface information;
- `ModuleVariables`;
- `UnsupportedPublicDeclaration`.

This is separate from parsing: source parsing describes authored declarations,
while module-surface inspection determines what a complete generated stub must
preserve.

### Emission

`compiler.emission` owns deterministic rendering of stub IR as Python stub text.
Its primary interface remains `emit_stub_module()`.

Current `emitter.py` moves to `emission/_python.py`.

### Pipeline

`compiler.pipeline` owns outer orchestration and generated results:

- `generate_module()`;
- `GeneratedModule`;
- `EmissionError` and `GenerationError`;
- conversion and composition of stage results.

Replacing `pipeline.py` with a `pipeline` package preserves imports such as:

```python
from typeforge.compiler.pipeline import GeneratedModule, generate_module
```

Initially, `pipeline.__init__` continues to re-export the compiler helpers used by
CLI, overlay, and verification. No inner compiler package may import the pipeline
facade.

## Dependency direction

```text
pipeline
  -> module_surface
  -> adaptation
  -> record_materialization
  -> specialization
  -> emission

record_materialization
  -> source
  -> stub_ir
  -> semantic_adapter
  -> emission

adaptation
  -> source
  -> stub_ir
  -> semantic_adapter        # after the schema cutover

module_surface
  -> source
  -> stub_ir

specialization
  -> stub_ir

emission
  -> stub_ir

semantic_adapter
  -> source
  -> stub_ir
  -> typeforge.semantics
```

Shared semantic record data may appear in record-materialization interfaces, but
compiler-specific semantic lowering, `TypeSystem` behavior, and schema evaluation
belong to `semantic_adapter`.

## Architecture rules

Add compiler topology to `tests/architecture/definitions.py` and enforce that:

- compiler package dependencies contain no cycles;
- `source` and `stub_ir` do not import another compiler domain;
- `record_materialization` does not import `adaptation`;
- inner compiler packages do not import `pipeline`;
- specialization and emission depend only on stub IR within the compiler;
- modules outside an owning compiler package do not import its underscore-prefixed
  implementation modules;
- modules outside `typeforge.compiler` consume supported compiler package
  interfaces rather than implementation files;
- `typeforge.semantics` does not import compiler types or compiler control data.

Tests should mirror the compiler package structure and specify behavior through
package interfaces. Do not preserve tests that couple consumers to private
implementation files merely because those tests already exist.

## Implementation sequence

### Working method: seam-first TDD

Treat each proposed package as an unproven module until its consumer seam has been
defined and exercised. Do not create all packages and move all files first.

For each package:

1. Inventory its current consumers and the behavior each consumer obtains from it.
2. Propose the smallest package interface that can provide that behavior. Record
   its inputs, outputs, invariants, ordering, and modeled failures, and confirm the
   seam before writing a test.
3. Add one failing contract test through the proposed package interface. The test
   must describe consumer-observable behavior rather than imports, dataclass
   layout, helper calls, or private implementation details.
4. Move only enough existing implementation to make that contract pass.
5. Route the corresponding real consumer through the new interface and run that
   consumer's focused tests.
6. Repeat one behavior at a time. Let each completed tracer bullet inform the next
   interface decision rather than specifying an entire imagined test suite in
   advance.
7. Delete the old definition only after every consumer of that behavior uses the
   new package interface.
8. Add or activate the architecture rule that protects the proven seam, then run
   the package contracts and affected consumer tests together.

A package slice is complete only when its interface contracts and migrated
consumer tests are green, the old path has no callers, and the diff contains no
unrelated semantic change.

### Package order

The order below follows the compiler dependency direction. The interface listed
for each package is a candidate to confirm at the start of that slice, not a
pre-approved test inventory.

1. **Authored source — `compiler.source`**

   Identify the parser, adaptation, semantic-lowering, record-materialization, and
   module-surface consumers. Establish the source model, parsing, marker
   normalization, and source-expression queries as the authored-source seam.
   Drive each exported behavior through `compiler.source`; only then remove
   `model.py`, `frontend.py`, and root `_markers.py`.

2. **Stub IR — `compiler.stub_ir`**

   Identify the adaptation, specialization, emission, record-materialization,
   module-surface, overlay, and verification consumers. Establish the IR data
   vocabulary and its exhaustive tree operations as the seam. Extract
   substitution and import normalization only when a consumer contract requires
   them. Remove the data section of `lowering.py` and `_type_tree.py` after all IR
   consumers use the package interface.

3. **Emission — `compiler.emission`**

   Establish deterministic `StubModule`-to-text rendering as the seam used by the
   pipeline and record rendering. Move one rendering capability at a time behind
   `emit_stub_module()` and related confirmed interface functions, then remove
   `emitter.py`.

4. **Finite specialization — `compiler.specialization`**

   Establish configured `StubModule -> StubModule` specialization and its modeled
   failures as the seam used by the pipeline, overlay, and existing compiler
   interface. Characterize `Each`, `Collect`, and callable `Map` behavior through
   that interface before moving each path out of `lowering.py`.

5. **Compiler semantic adapter — `compiler.semantic_adapter`**

   Identify record-materialization and future schema-adaptation consumers.
   Establish compiler static types, source-to-semantic lowering, and the
   `TypeSystem` adapter as one explicit seam with shared semantics. Migrate the
   existing strict contracts to this package interface before moving
   `records.py`, `_semantic_lowering.py`, and `_type_system.py`.

6. **Source adaptation — `compiler.adaptation`**

   Identify pipeline, overlay, verification, and record-related consumers.
   Establish authored-source-to-stub-IR adaptation, callable relationship aliases,
   and authored diagnostics as the seam. Move behavior vertically and quarantine
   the duplicate schema implementation in `_legacy_schema.py` only after its
   remaining callers are characterized.

7. **Module surface — `compiler.module_surface`**

   Establish public-surface validation and extraction as the seam used by the
   generation pipeline. Drive validation, public imports, and module-variable
   preservation through consumer-visible contracts before moving their logic out
   of `_pipeline_utils.py`.

8. **Record materialization — `compiler.record_materialization`**

   Identify pipeline and overlay consumers. Establish record discovery,
   `MapFields` materialization, generated declarations, replacements, and modeled
   failures as the seam. Remove the dependency on adaptation through contracts at
   the record interface rather than by sharing internal helpers or error models.

9. **Generation pipeline — `compiler.pipeline`**

   Once the inner seams are proven, establish orchestration from a source path to
   `GeneratedModule` as the final compiler seam. Convert `pipeline.py` into a
   package, dissolve `_pipeline_models.py` into the owning packages, and preserve
   the currently supported downstream imports through `pipeline.__init__`.
   Pipeline tests should verify stage composition and authored failure propagation,
   not reproduce the contracts owned by inner packages.

10. **Architecture closure**

    Complete the compiler topology in `tests/architecture/definitions.py`, enable
    the full dependency rules, verify that no consumer imports a private
    implementation module, and run `make check`.

Prefer move-only implementation steps where possible so Git preserves rename
history. Structural movement happens inside each red-green package slice rather
than as one horizontal move of the entire compiler. Keep algorithmic changes out
of this task; any necessary model correction must be isolated, justified by a
consumer contract, and described explicitly.

## Completion criteria

- Every existing compiler file and public symbol has an explicit owning package.
- `model.py`, `records.py`, `_pipeline_models.py`, and `_pipeline_utils.py` no
  longer exist as ambiguous compiler-root buckets.
- Existing generated-stub and overlay behavior is unchanged.
- Existing supported `typeforge.compiler.pipeline` imports continue to work.
- Compiler tests mirror the new package structure.
- Architecture tests enforce the intended dependency graph and pass.
- No duplicate implementation is introduced during the move.
- `make check` passes.
- The deferred-map compiler cutover can resume against the explicit
  `semantic_adapter` and `adaptation` seams.
