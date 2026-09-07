# Pydantic Integration Redesign

Status: In progress — slice 1 complete; next: replacement pipeline (slice 2)

Priority: Next implementation scope

Deferred follow-up: [Callable Map semantics cutover](../ideas/callable-map-semantics-cutover.md)

Integration follow-up: [Compiler integration diagnostics](../ideas/compiler-integration-diagnostics.md)

Slice 1 contracts and handoff: [Runtime characterization](pydantic-characterization.md)

## Goal

Replace the private Pydantic implementation while preserving the public
`from typeforge.pydantic import Input, Schema` interface. Adapt runtime typing
objects to shared semantic expressions, evaluate through `typeforge.semantics`,
and emit Pydantic schemas from the results. Delete the independent runtime
expression model and evaluator when the replacement is complete.

The objective is consistent Typeforge meaning across compiler Schemas and
runtime validation, with clear ownership of parsing, evaluation, and emission.
Splitting the existing file without removing semantic duplication is insufficient.

Generic BaseModel field integration is an acceptance requirement for this
replacement. It must work through the existing Schema annotation without a
Typeforge-specific model base class, metaclass, or model mutation pass.

## Current state and completed prerequisites

The eight-slice compiler Schema migration is complete. Shared semantics now owns
ordered Map evaluation, structural patterns and repeated Value captures, nested
output templates, three-way unresolved static decisions, MapFields transforms,
and DeferredMap representation and possible-output composition. Production
compiler Schema boundaries consume it; the legacy Schema evaluator is deleted.
Callable Map specialization remains a separate deferred scope.

The completed compiler task documents have been removed. Their executable
contracts remain in:

- `tests/unit/compiler/pipeline/test_schema_map_characterization.py`;
- `tests/unit/compiler/pipeline/test_schema_map_corrections.py`;
- `tests/unit/compiler/adaptation/test_schema_adapter.py`;
- `tests/unit/semantics/`.

Pydantic currently exposes its markers through `src/typeforge/pydantic/__init__.py`
and implements parsing, a private expression model, evaluation, structural
matching, record adaptation, deferred RuntimeMapPlan dispatch, and CoreSchema
emission in `src/typeforge/pydantic/_schema.py`. It does not yet consume shared
evaluation. Existing tests provide a behavioral oracle, not an implementation
template for the replacement.

DeferredMap already preserves ordered cases, default, context, and possible
output. That does not settle how a runtime consumer resumes selection from raw
input. Define that seam before implementing deferred validation.

## Responsibility boundaries

| Responsibility | Owner |
| --- | --- |
| Model specialization, inherited field substitution, model configuration, rebuild lifecycle | Pydantic |
| Marker recognition, arity, aliases, alias argument binding, Python typing reflection | Runtime frontend |
| Generic fallback precedence and integration-specific acceptance rules | Pydantic integration policy |
| Schema construction lifecycle and readiness handling | Pydantic runtime integration |
| Ordered Map selection, predicates, structural matching, captures, output bounds, field transformations | Shared semantics |
| Equality, assignability, unions, parameterized type inspection/construction | Runtime TypeSystem adapter |
| TypedDict inspection and field metadata | Explicit runtime record adapter |
| Raw input observation, validation strategy, serializers, CoreSchema and JSON Schema | Pydantic integration |
| Modeled failures translated to authored Pydantic-facing diagnostics | Integration boundary |

Target pipeline:

```text
Pydantic field hook's current source type (possibly still generic)
    -> runtime frontend
    -> compilation readiness / Pydantic generic fallback policy
    -> shared semantic expression
    -> shared evaluation
    -> resolved, unresolved/indeterminate, or DeferredMap result
    -> Pydantic emission
    -> CoreSchema
```

Keep orchestration free of expression-specific rules and schema construction.
A possible private organization is `_annotation.py`, `_compile.py`,
`_frontend.py`, `_type_system.py`, `_records.py`, `_emission.py`, and `_errors.py`.
Choose cohesive modules as slices land; these names are not a requirement to
create empty scaffolding. Add a planning module only if strategy selection
becomes a substantial responsibility.

TypeSystem operations must remain primitive: they do not receive whole Maps or
perform pattern matching and capture. Semantics has no knowledge of raw input
values, Pydantic model internals, validators, serializers, CoreSchema, or compiler
IR. Backend type references may carry opaque Python types, including model
classes; their interpretation stays in the adapter.

### Separation needed by the future compiler plugin

Keep Pydantic-specific rules separate from both general Typeforge semantics and
Pydantic execution. Runtime and static consumers need the same generic fallback
and acceptance policy, but neither consumer should import the other's frontend
or schema machinery.

Keep the following rules cohesive and separate from schema emission within the
Pydantic integration; a private _policy.py is sufficient if a separate file helps:

- selection of default, constraints, bound, or Any from adapted parameter facts;
- classification of integration-invalid semantic outcomes, such as no matching
  Map case without a default;
- integration restrictions such as the supported value-time pattern language,
  where the decision is independent of raw-value observation and execution.

Policy consumes Typeforge-owned facts and shared semantic results and returns
typed decisions/issues. It must not perform Python reflection, source parsing, pattern
matching, schema construction, or diagnostic formatting. Preserve provenance
needed to distinguish explicit arguments from defaults or bounds when validation
and serialization differ. Introduce only the data required by actual rules, not
a general plugin context or capabilities framework.

Keep this policy inside typeforge.pydantic. The future compiler loader guards
the optional integration import: when Pydantic is unavailable, it does not load
the Pydantic plugin. When installed, the plugin may import the integration and
reuse its policy. There is no requirement for that policy to be independently
importable without Pydantic, and no separate dependency-free package is needed.
The guard handles missing optional dependencies specifically; unrelated import
failures must remain visible. Plugin loading itself is follow-up work, not part
of this first pass.

Runtime reflection adapts Python TypeVars and aliases into policy facts; the
future compiler plugin will adapt source facts into the same concepts. General
Map matching stays in semantics. The policy module interprets an outcome for
the integration; runtime code converts issues to Pydantic exceptions, while a
future compiler adapter attaches authored source spans and checker diagnostics.
Keep issue identity and relevant expression/operand information until those final
presentation seams. Do not make consumers parse exception messages or infer
Typeforge errors from CoreSchema generation failures.

Preserve evidence required for that classification. Shared Map evaluation
currently returns the backend empty union (Never) when no case matches and no
default exists. The same output may be explicitly selected by a case or default.
The replacement must retain enough semantic outcome information to distinguish
these paths, including nested expressions, without implementing another matcher
in policy or running a separate diagnostic evaluator. Extend the existing
semantic result/selection seam only as needed by the runtime no-match contract;
the compiler's emitted type can still be Never. A full evaluation trace is not
required.

Test policy decisions independently of schema emission, language rules through
shared semantics, and validation/serialization through actual Pydantic. Preserve
base Typeforge's optional dependency isolation. The future loader must be tested
with Pydantic available and absent. Static analysis of generic use sites and
plugin dispatch remain follow-up work; runtime is the first policy consumer.

## Generic model fields and schema construction lifecycle

The following is a required outcome, including successful definition of the
generic origin before any specialization exists:

```python
from pydantic import BaseModel
from typeforge import Case, Map
from typeforge.pydantic import Schema

class Payload[T](BaseModel):
    value: Schema[Map[T, Case[int, str], Case[bytes, int]]]

assert Payload[int](value="3").value == "3"
assert Payload[bytes](value="3").value == 3
```

There are three different states to preserve:

| State | Required handling |
| --- | --- |
| Concrete type arguments | Evaluate now and emit the selected output schema. |
| Unparametrized runtime type arguments | Apply Pydantic's default, constraints, bound, or Any policy for this schema build; retain the authored expression for later specialization. |
| Authored runtime Input | Build deferred validation that observes each raw input value. |

An unresolved model parameter is not Input. Nor does a static possible-output
bound automatically authorize validating against that union: doing so could
erase the relationship the user authored.

Pydantic owns substitution of model parameters into field annotations. The
frontend consumes the source supplied on each hook invocation and binds the
Typeforge aliases found within it. Keep parameter-dependent expressions in the
typing arguments of Schema, where Pydantic can substitute them. Do not move them
solely into opaque Annotated metadata or cache a result on the shared metadata
instance. Rebuild and concrete specializations must recompile from their current
source, retaining the original annotation for subsequent specialization.

The generic origin and partially specialized subclasses must be constructible
without a blanket requirement to supply type arguments. The selected policy is
to follow [Pydantic's unparametrized type-variable behavior](https://pydantic.dev/docs/validation/dev/concepts/models/#validation-of-unparametrized-type-variables),
superseding the earlier proposal to reject validation until specialization:

- use a declared type default when applicable;
- otherwise use the declared constraints or bound;
- otherwise use typing.Any.

Match the supported Pydantic version's precedence when declarations combine a
default with a bound or constraints. Pydantic 2.13.4 checks the default first,
then constraints, then the bound, then Any. Compare against ordinary Pydantic
generic fields in executable contracts instead of importing private helpers.

This is a runtime schema policy, not a change to compiler reasoning about
unresolved static identity. A bound does not prove that a static parameter is
exactly the bound; using it for unparametrized runtime validation is deliberate
Pydantic behavior. Preserve the authored parameter and its provenance so concrete
specialization recompiles with the actual argument. Never infer a missing type
argument from the raw value or convert it into runtime Input.

Ordinary Schema[T] should delegate directly to Pydantic. For Typeforge
transformations, the runtime adapter must make the effective generic fallback
available to semantic evaluation without duplicating language rules. Pydantic's
guidance defines generic fallback; Typeforge's accepted Map policy below defines
exact and structural matching against Any. Slice 1 must turn that policy into
executable contracts and characterize constrained alternatives and predicates.
No-match, invalid record operands, and unsupported capture remain distinct from
an error merely saying that specialization is required.

In particular, neither Any nor an opaque T supplies structural arguments for a
Value capture or fields for MapFields. Characterize those outcomes and their
construction/validation timing while preserving the ability to create valid
concrete specializations. Do not fabricate structure or suppress unrelated
invalid expressions. Prove the lifecycle with public hooks; do not require
private Pydantic generic metadata or defer_build=True.

Retain validation and serialization distinctions as well as the validation
fallback. For example, Pydantic can validate an unparametrized model-bound TypeVar
against its bound while serializing it as Any. Replacing every occurrence with
the bound would lose that behavior. Delegate retained TypeVars where possible
and preserve the necessary provenance through transformations; test bound,
constrained, defaulted, and explicit-Any cases in both modes.

### Accepted Any matching and no-default policy

Here Any means typing.Any, not Typeforge's Any condition operator. These rules
apply equally to explicit Any and Any supplied by Pydantic's generic fallback:

- Exact cases compare type identity. Any does not match an exact int case; an
  explicitly authored exact Any case can match it.
- Structural cases require known structure. Bare Any does not match list[Value]
  and does not invent a capture. list[Any] does match list[Value], capturing Any.
- A mismatch continues to the next authored case, then the authored default.
  This preserves first-match ordering and does not inspect raw input values.
- When no case matches and no default exists, the Pydantic integration raises
  an exception explaining that the Map cannot determine an output type from Any.
  It must not silently accept the value as Any, infer a type from the value, or
  validate against an invented union of case outputs.

For example:

| Expression | Runtime schema outcome |
| --- | --- |
| Map[Any, Case[int, str], Default[bytes]] | bytes |
| Map[Any, Case[list[Value], set[Value]], Default[Any]] | Any |
| Map[list[Any], Case[list[Value], set[Value]]] | set[Any] |
| Map[Any, Case[int, str]] | Exception: no matching case and no default |
| Map[Any, Case[list[Value], set[Value]]] | Exception: no matching structure and no default |
| Map[Any, Case[Any, str]] | str; no default is needed because a case matches |

The exception rule is for an unmatched Map, not every Map lacking a default.
This records runtime behavior; it does not change the compiler's Never output
for a no-match path. Nor does it redefine unresolved static T as concrete Any.

Slice 1 must fix the diagnostic and failure timing at the public Pydantic seam.
Direct invalid schemas and validation of an unparametrized generic must surface
the failure while preserving the ability to define the generic class and create
a valid concrete specialization. Explicit Default[Never] remains distinct from
omitting a default. Predicate cases, including Assignable, retain their own
contracts; the exact-type rule is not an assignability rule.

### Model fields versus model transformation

Schema expressions on a BaseModel field, including generic fields, do not need
a BaseModel record adapter. Pydantic retains model construction, field aliases,
defaults, validators, configuration, private attributes, and serialization.
Concrete model classes selected as field output types delegate to Pydantic.

`MapFields[SomeBaseModel, ...]` would transform the model itself and remains a
separate feature requiring explicit output identity and field behavior. Likewise,
structurally capturing parameters from a Pydantic model class is not implied by
supporting model classes as opaque output types. Python get_origin/get_args do
not expose specialized BaseModel arguments like ordinary generic aliases.

### Handler composition, references, and isolation

Keep the schema handler local to its construction call. Use its continuation
when preserving the current annotation's middleware, and `generate_schema` for
independent output or child types where that context must not leak. Test metadata
on both sides of Schema, field validators/serializers, constraints, and nested
model outputs; delegation must neither discard metadata nor apply it twice.
See Pydantic's [custom type hooks](https://docs.pydantic.dev/latest/concepts/types/#customizing-validation-with-__get_pydantic_core_schema__)
and [schema handler interface](https://docs.pydantic.dev/latest/api/annotated_handlers/#pydantic.annotated_handlers.GetCoreSchemaHandler.generate_schema).

Avoid new global CoreSchema caches. Pydantic owns model and alias definitions;
Typeforge owns references only for synthesized shapes. Those references must
distinguish generic specializations and reuse equivalent shapes within one schema
build. Verify that constructing Payload[int] before Payload[bytes], or the reverse,
does not change validation, serialization, or JSON Schema.

Unresolved forward names are also distinct from invalid Typeforge expressions.
Preserve Pydantic's supported deferred construction and model_rebuild lifecycle
for ordinary references. A missing name encountered while expanding a Typeforge
alias needs a deliberate translation at the hook, rather than an unconditional
permanent schema error. Recursive Typeforge aliases remain unsupported. See
[annotation rebuilding](https://docs.pydantic.dev/latest/internals/resolving_annotations/#resolving-annotations-when-rebuilding-a-model).

### Review evidence

Local probes on Python 3.14.3 and Pydantic 2.13.4 established the following:

- The hook receives a Typeforge alias with T during generic class definition,
  then the alias with int or bytes for concrete specializations; forced rebuild
  invokes it again with the specialized source.
- Current `Schema[T]` and some generic Maps with defaults work. An exact Map
  without a default fails during generic class definition by resolving to Never;
  a Map with a default prematurely selects that default for unresolved T.
- `Schema[MapFields[T, ...]]` currently fails while defining the generic origin,
  even when the intended later argument is a supported TypedDict.
- A parameter-dependent expression stored inside Annotated metadata retains T
  even when the annotated source is specialized to int.
- A small annotation-hook probe that rejects unresolved value validation while
  allowing schema construction successfully exercised concrete specializations,
  forced rebuild, generic inheritance, structural Maps, and TypedDict MapFields.
  This proves lifecycle feasibility only: it used the old evaluator for concrete
  cases and is not a replacement frontend or a production implementation. Its
  rejection policy was subsequently superseded by the selected Pydantic fallback
  policy above; do not copy that policy into the replacement.
- A missing name inside a Typeforge alias currently becomes a fatal alias error
  before the model can be rebuilt.

The review supports the proposed module responsibilities, with lifecycle handling
added to the first implementation gate. Slice 1 now supplies durable public
characterization and a Pydantic hook lifecycle proof, plus one strict pending
contract. See the companion matrix for retained behavior and corrections; full
generic transformation support is not implemented yet.

## Behavior to preserve

- Schema returns the resolved value without a public wrapper and works through
  TypeAdapter and BaseModel fields.
- Ordinary types and metadata delegate to Pydantic, using the handler's
  `generate_schema` operation for ordinary resolved types.
- Schema-time transformations resolved from explicit arguments or Pydantic's
  generic fallbacks add no Typeforge evaluation callback to individual validations.
- Maps retain authored order, predicates, defaults, union behavior, structural
  captures, and nested output reconstruction.
- Input dispatch inspects raw input before branch coercion, selects the first
  matching case, and validates only the selected output. Private dispatch data
  must not appear in returned or serialized values.
- An unmatched Input without a default raises `typeforge_map_no_match`.
- TypedDict MapFields preserves transformed field types, requiredness,
  readonly information, metadata, and nested error locations; rename and Drop
  retain their meanings. Other record families fail explicitly.
- Ordinary recursive aliases delegate to Pydantic. Recursive aliases containing
  Typeforge operators fail explicitly until that capability is designed.
- Construction failures retain stable codes and authored operator vocabulary.
  Convert expected failures to PydanticSchemaGenerationError once at the metadata
  hook; convert per-value no-match at validation. Unexpected failures propagate.
- Definitions and references remain deterministic and avoid collisions.
- Importing base Typeforge does not import the optional Pydantic dependency.

Use actual Pydantic in integration tests. Assert observable behavior at Schema,
and shared language rules at the semantics interface. Avoid freezing unrelated
CoreSchema layout or introducing a broad mock schema protocol.

## Deferred dispatch decisions

Slice 1 classifies the old implementation's behavior in the
[runtime contract matrix](pydantic-characterization.md). The following decisions
govern the replacement; the companion document defines the resumption seam,
supported language, diagnostics, and serialization limits in detail.

1. **Value-time pattern language.** Concrete runtime cases use exact raw type
   matching; predicates can express assignability. The existing matcher also
   handles unions, Annotated, and Literal values. Retain those forms and match
   Literals by both type and value, as confirmed during slice 1: True does not
   match Literal[1]. Parameterized runtime patterns remain unsupported, including
   when nested under unions, annotations, or aliases.
2. **Resuming deferred meaning.** Shared semantics owns ordered selection and
   returns chosen-branch/context or no-match evidence. Runtime adaptation supplies
   on-demand test decisions for the supported observation language; shared
   predicates evaluate with the raw input type bound in context. Keep raw values
   outside semantics and avoid another ordered selection loop. A possible-output
   union is not a dispatch plan. Nested Maps retain their own contexts.
3. **Predicate failures.** The old dispatcher catches SchemaIssue and treats it
   as a mismatch. Correct this: a reached modeled failure propagates with its
   authored diagnostic; unvisited operands remain unvisited. Output validation
   failure does not resume matching or try the default.
4. **Serialization.** The current implementation infers an output branch from
   the returned value, rather than preserving the original validation branch.
   Preserve tested unambiguous output behavior. Original-branch serialization for
   indistinguishable overlapping outputs is outside this pass; do not promote
   the old heuristic into a permanent promise or add a public wrapper.

An empty JSON Schema for deferred validation input is an honest temporary
behavior, not a permanent compatibility requirement. A complete raw-input schema
and ambiguous-output serialization redesign remain separate unless needed for
the agreed replacement contract.

## Implementation slices

Every slice should be independently reviewable. Start from observable contracts,
run focused `make check <source and test paths>` while developing, and finish
with full `make check`. Add architecture protection alongside the boundary it
protects. Mark a slice complete only after its tests and deletion obligations pass.

### 1. Characterize the runtime contract and prove generic lifecycle support

Complete. Production code is unchanged. The
[characterization matrix](pydantic-characterization.md) records retained behavior,
corrections C1–C9, a generic-hook lifecycle proof, and the single strict xfail
tracer for the no-default generic Map. The existing test inventory includes
`tests/unit/pydantic/test_schema.py`, `test_structural_map.py`, `test_input.py`,
`test_map_fields.py`, `test_json_schema.py`, and `test_errors.py`, plus optional
dependency coverage in `tests/unit/runtime/test_imports.py`.

Add missing public contracts for alias/generic binding, repeated captures and
failed captures, nested outputs, raw-input ordering and strictness, selected-branch
failure without fallback, serialization, and failure propagation. Reuse existing
coverage rather than duplicating it. Classify gaps, generic lifecycle policy, and
the four deferred-dispatch decisions above in a behavior matrix; distinguish
supported behavior from incidental implementation.

Make generic field support an early feasibility gate: generic origin definition,
direct and aliased Maps with no default, concrete and partial specialization,
traditional TypeVar/Generic and PEP 695 forms, inheritance, same-symbol identity,
known structural positions versus opaque T, bounds/constraints/defaults/Any,
ordinary forward references and model_rebuild, and specialization isolation.
Cover Schema both directly on a field and nested in a container. Include
validation and serialization modes, JSON Schema, field metadata, and model
configuration. Cover every accepted Any policy row above, equivalent explicit
and fallback Any, and both successful specialization and unparametrized no-match
failure for a generic Map without a default. Name the exception phase and
diagnostic at each public entry point.

Completion: retained contracts pass, each intended correction names its owning
seam and later slice, the Pydantic-compatible generic hook strategy is demonstrated
without a custom model base, and the supported Input language and shared
selection responsibilities are recorded. Direct no-match schema construction and
unparametrized generic validation have explicit exception phases. Slice 2 can
implement the private replacement; the public tracer remains pending until the
slice 6 cutover.

### 2. Establish the replacement pipeline for resolved types and Maps

Next slice; not started.

Build a private orchestration seam with runtime adaptation, a TypeSystem adapter,
shared evaluation, Pydantic generic fallback/emission policy, ordinary-type emission,
and one error conversion boundary.
Keep reusable integration policy separate from schema emission as described above,
and preserve the semantic no-match evidence its classification requires. Do not
infer no-match solely from an emitted Never type.
Cover ordinary types, metadata, exact Maps, conditions, defaults, unions, and
schema-time no-match. Include a generic BaseModel with a direct Map field in this
first vertical implementation: the origin must exist and two concrete
specializations must behave independently. Test the replacement through a private
annotation hook using actual Pydantic while the public hook continues to use the
existing implementation.

Completion: this supported family runs end to end without calling the old
parser, expression model, evaluator, or emitter, including modeled and unexpected
failure contracts, generic construction/rebuild behavior, and the
no-per-validation-callback guarantee for fully resolved transformations.

### 3. Complete runtime aliases and structural expressions

Extend the same pipeline for PEP 695 aliases, generic and variadic binding,
Unpack, structural patterns, repeated captures, nested Maps and output templates,
and contextual Literal roles. Preserve opaque typing objects and metadata.
Handle alias cycles explicitly and delegate ordinary recursive aliases.
Preserve authored parameter identity and expressions across runtime fallback
evaluation and concrete specialization. Do not add a second substitution engine
for Pydantic model fields or indiscriminately erase parameters to Any; apply Any
only where the selected Pydantic fallback policy calls for it.

Completion: structural and alias contracts pass through shared semantics;
runtime type inspection/building contains no duplicate matcher or capture logic.
Generic alias fields, partial specializations, and rebuilt concrete models pass
the lifecycle contracts from slice 1.

### 4. Integrate TypedDict records and MapFields

Adapt TypedDicts to family-aware shared RecordShape data. Evaluate field
transformations through semantics and emit synthesized schemas, preserving
inherited fields, requiredness, readonly information, constraints, documentation,
error locations, and deterministic references. Include MapFields[T, ...] on a
generic BaseModel field specialized with a TypedDict. Reject unsupported record
families after the subject is known.

Completion: record validation, serialization, and JSON Schema contracts pass
through the replacement pipeline, including duplicate rename and invalid output
failures. Ordinary leaf schemas still delegate to Pydantic.

### 5. Integrate deferred Input selection and emission

Implement the runtime observation/selection seam agreed in slice 1 and any needed
shared semantic extension at its owning interface. Consume DeferredMap directly;
retain semantic case ordering and context, then build the private validation
strategy. Validate the selected output without leaking dispatch data.

Completion: Python and JSON input, strict ordering, predicates, defaults,
no-match, nested deferred cases, unsupported patterns, serialization, and failure
contracts pass. Include generic fields combining bound static parameters with
runtime Input; a missing model parameter must not be supplied from a raw value.
No old RuntimeMapPlan or private evaluator is used by this path.

### 6. Switch the public hook and remove the old implementation

Route Schema metadata through the replacement orchestration seam. Run all
behavior tests at the public interface and delete the old expression model,
evaluator, structural matcher, RuntimeMapPlan, and superseded emission helpers.
Remove obsolete imports and tests tied only to deleted internals.

Completion: one semantic implementation serves compiler Schemas and Pydantic;
there is no production fallback or compatibility bridge to the old evaluator.
Architecture tests enforce supported semantics imports, no dependency between
compiler and Pydantic implementations, frontend/emission separation, private
CoreSchema construction, acyclic dependencies, and optional dependency isolation.
Public documentation reflects supported behavior and full `make check` passes.

## Outside this scope

Plugin-style compiler support for integration-specific type diagnostics is a
follow-up. It should eventually report statically detectable integration failures,
such as an unmatched Any Map without a default, before runtime. This pass records
the runtime contracts and modeled diagnostics that those checks can reuse; it
does not build a plugin interface or add compiler diagnostics. Valid generic
declarations must remain distinct from invalid unparametrized uses.

Callable Map compiler unification; BaseModel record transformation and structural
capture of BaseModel generic arguments (generic field integration is in scope); recursive
Typeforge aliases; a public adapter registry or explanation API; configurable
execution strategies; a new shared runtime package; and dependency upgrades
unless a demonstrated requirement makes one necessary. Preserve `uv.lock` unless
dependencies actually change.

## Immediate next action

Implement slice 2 using the [contract handoff](pydantic-characterization.md).
Start with the no-default generic Map tracer through the private replacement
annotation hook, then add generic fallback and typed no-match outcomes. Retain
the public strict xfail until the complete production cutover in slice 6.
