# Deferred Map production characterization

Slice 1 of [Deferred Map Semantics and Compiler Cutover](deferred-input-map-semantics.md).
Classified against compiler baseline `7314f36` on 2026-09-06, using the current
`generate_module()` boundary and the failure inventory in experiment `49356b9`.
Production code is unchanged by this slice.

Validation: all 62 retained characterization cases and the focused existing
compiler-plan compatibility checks pass. Full `make check` passes pytest, Ruff
lint and format checks, Flake8 block spacing, mypy, and pyright. Every retained
parameter ID is indexed below; C1–C13 remain documentation-only corrections.

## Classification and test policy

**Retained** means the production result is already the intended result. It does
not mean shared semantic lowering or evaluation can produce it yet. In particular,
union output templates and nested deferred outputs work through the legacy
compiler evaluator today.

**Correction** means the production result needs to change. The examples below
record current observations and desired outcomes without asserting wrong output
in tests. Before implementing a correction, add its strict failing contract at
the named owning interface and remove that xfail in the same slice. Add the
corresponding `generate_module()` correction test in slice 8.

The retained cases are executable in
[`test_schema_map_characterization.py`](../../tests/unit/compiler/pipeline/test_schema_map_characterization.py).
The IDs below are pytest parameter IDs; that file contains the full authored
expressions and expected generated interfaces. Each parameter generates a
separate module so failures identify one contract rather than one large fixture.

## Retained behavior

### Concrete types, output roles, and traversal

These IDs belong to `test_schema_maps_preserve_type_outputs` unless stated
otherwise. The migration column names the prerequisite that must preserve the
behavior, followed by the schema adapter and cutover in slices 7–8.

| Test ID | Retained result or rule | Migration prerequisite |
| --- | --- | --- |
| `direct-structural` | `list[int]` captured by `list[Value]` produces `set[int]`. | Existing structural semantics |
| `literal-output`, `literal-default` | Selected case and default outputs retain `Literal["accepted"]` and `Literal["rejected"]` as typing types. | Slice 2: explicit output role |
| `literal-case` | Equal typing literals match an exact case. | Slice 2: explicit case role |
| `literal-predicate`, `literal-assignable` | Typing literals work as `Equal` and `Assignable` operands. | Slice 2: explicit operand role |
| `union-output` | `set[Value]` inside a union becomes `set[int]`, retaining `None`. | Slice 2: output-template composition |
| `nested-union-output` | `tuple[Value \| None]` becomes `tuple[int \| None]`. | Slice 2: recursive output role |
| `union-subject` | Each member selects its own output, producing `str \| float`. | Shared union-subject evaluation |
| `normalized-subject`, `normalized-pattern` | `list[int \| int]` and `list[int]` match after nested normalization, on either side. | Slice 2 lowering and slice 7 nested-type adaptation |
| `normalized-output` | Captured `Value \| int` normalizes inside `tuple` to `tuple[int]`. | Slice 2: output-template composition |
| `under-application` | A Map beneath `list` resolves to `list[str]`. | Slice 7: recursive schema adaptation |
| `under-union` | A Map beneath a union resolves to `str \| None`. | Slice 7: recursive schema adaptation |
| `under-starred` | A Map beneath an unpack resolves to `tuple[*tuple[str, bytes]]`; preserve the existing spelling. | Slice 7: recursive schema adaptation |
| `nested-schema` | A nested `Schema` beneath `tuple` resolves to `tuple[str, int]`. | Slice 7: schema-boundary traversal |
| `nested-capture-map` | A nested Map consumes the enclosing structural capture and selects `str`. | Slice 2 role composition and slice 7 adaptation |

### Deferred outputs and defaults

These IDs also belong to `test_schema_maps_preserve_type_outputs`.

| Test ID | Retained result or rule | Migration prerequisite |
| --- | --- | --- |
| `deferred` | Runtime Input contributes ordered possible outputs `int \| bytes`. | Existing `DeferredMap` contract |
| `deferred-predicate` | A predicate over runtime Input contributes its output plus the default: `int \| float`. | Existing deferred contract and slice 7 adaptation |
| `nested-deferred` | A deferred case output contributes `str \| float` to the outer result `str \| float \| bytes`. | Slice 3: possible-type composition |
| `union-deferred-outputs` | Deferred outputs from a union subject contribute `bytes \| float`, without a duplicate `bytes`. | Slice 3: possible-type composition |
| `duplicate-deferred` | Identical outputs across cases and default normalize to `str`. | Shared union normalization |
| `deferred-omitted`, `deferred-explicit-never` | Both emit `str`; a no-match path contributes no output type. | Slices 3 and 7 |
| `deferred-all-never` | No inhabited possible output emits `Never`. | Slices 3 and 7 |
| `no-match-omitted`, `no-match-explicit-never` | A concrete unmatched Map emits bare `Never` in either spelling of the default. | Slice 7: typing emission policy |
| `union-no-match` | An unmatched union member contributes no output, leaving `str`. | Shared union-subject evaluation |

Equal static output for an omitted default and `Default[Never]` does not justify
erasing their source distinction. Slice 6 must preserve it for shared semantics.
The static `Never` tests do not define runtime no-match handling.

### Unresolved generics and ordered selection

These IDs belong to `test_generic_schema_maps_preserve_reachable_outputs`.
All are retained production behavior that slices 4–5 must represent explicitly
in shared semantics before slices 7–8 can replace the legacy evaluator.

| Test ID | Retained result or rule |
| --- | --- |
| `unknown-predicate`, `unknown-assignable` | An unresolved comparison with `int` contributes `str \| bytes`. |
| `known-true-first`, `exact-first` | An earlier definite predicate or exact match selects only `float`. |
| `known-false-first` | A definite false condition falls through to the unresolved case and default: `str \| bytes`. |
| `unknown-then-unknown` | Two reachable uncertain cases followed by a default contribute `str \| float \| bytes`. |
| `unknown-then-match` | An uncertain case followed by a definite match contributes only `str \| float`; later cases and default are unreachable. |
| `unknown-no-default` | An uncertain case without a default contributes only `str`. |
| `same-symbol-exact` | An exact `T` case matches subject `T`, selecting `str`. |
| `same-structure` | `list[T]` matches itself, selecting `str`. |
| `known-origin-mismatch` | `list[T]` cannot match `set[int]`; select the default `bytes`. |
| `known-argument-mismatch`, `known-argument-mismatch-after-unknown` | A known differing tuple argument rules out a case, whether before or after an unresolved position. |
| `repeated-capture-same` | Repeated captures from `tuple[T, T]` agree and retain `T`. |
| `repeated-capture-mismatch` | Known unequal captures rule out a case even with a later unresolved argument. |
| `nested-uncertain-output` | A selected nested uncertain Map contributes `str \| bytes`. |
| `uncertain-deferred-output` | An uncertain case with a deferred output composes to `str \| float \| bytes` (also requires slice 3). |
| `nested-uncertain-predicate` | A predicate consuming an uncertain Map remains uncertain and contributes `bytes \| float`. |
| `all-unknown-false` | A false operand makes `All` false despite an earlier unknown operand. |
| `any-unknown-true` | A true operand makes `Any` true despite an earlier unknown operand. |
| `not-unknown` | Negation preserves uncertainty, producing `str \| bytes`. |

The nested-predicate row already emits the desired union because the legacy
evaluator finds a variable anywhere in the operand tree. That conservative rule
does not preserve enough meaning for definite nested results; see correction C9.

### Aliases and field transforms

Alias IDs belong to `test_schema_relationship_aliases_preserve_type_outputs`.
They also assert the published `object` fallback of every relationship alias.

| Test ID | Retained result or rule | Migration prerequisite |
| --- | --- | --- |
| `structural-alias` | Bind alias parameter `A` to `list[int]` before capturing `Value`, producing `set[int]`. | Slice 6: source alias binding |
| `generic-alias` | Binding `A` to unresolved caller `T` retains `str \| bytes`. | Slices 4–6 |
| `alias-omitted`, `alias-explicit-never` | An unmatched alias use emits `Never` in either case; source distinction must still survive. | Slices 6–7 |
| `alias-in-argument` | `Outer[Inner[int]]` resolves the argument alias before outer case selection, producing `float`. | Slice 6: recursive alias binding |
| `alias-under-application`, `alias-under-union` | An alias beneath `list` or a union resolves to `list[str]` or `str \| None`. | Slices 6–7 |
| `alias-under-starred`, `alias-under-schema` | Alias expansion survives an unpack and nested Schema, producing `tuple[*tuple[str, bytes]]` and `tuple[str, int]`. | Slices 6–7 |

Field-transform IDs belong to
`test_schema_field_transforms_preserve_typing_emission`.

| Test ID | Retained result or rule | Migration prerequisite |
| --- | --- | --- |
| `literal-field-name` | A direct `Field[Literal["renamed"], Value]` renames the generated field and preserves `int`. | Slice 2: field-name role |
| `literal-field-name-case` | String literals in a Map over `Key` remain field-name case tests and outputs. | Slice 2: contextual case/output roles |
| `literal-field-name-predicate` | `Equal[Key, Literal["original"]]` compares field names and selects the renamed field. | Slice 2: contextual operand role |
| `field-value-never` | A transformed field with no matching type case emits `tf_typing.Never`. | Slice 7: reuse one StaticType emission policy |

## Intended corrections

For C1–C9, each expression is the argument of `Schema[...]` on a field of
`class Payload[T, U]`. All use `Default[bytes]` except C9 as shown. The owning
strict contracts belong to **slice 5, `evaluate()`**, after slice 4's model
contracts establish symbolic identity, partial structure, and provenance.
Compiler lowering of those model values belongs to slice 7; end-to-end
correction coverage belongs to slice 8.

| ID | Authored expression | Observed production output | Intended output |
| --- | --- | --- | --- |
| C1 `unknown-exact` | `Map[T, Case[int, str], Default[bytes]]` | `bytes` | `str \| bytes` |
| C2 `different-symbols-exact` | `Map[T, Case[U, str], Default[bytes]]` | `bytes` | `str \| bytes` |
| C3 `same-symbol-predicate` | `Map[T, Case[Equal[T, T], str], Default[bytes]]` | `str \| bytes` | `str` |
| C4 `same-symbol-assignable` | `Map[T, Case[Assignable[T, T], str], Default[bytes]]` | `str \| bytes` | `str` |
| C5 `unknown-structural-subject` | `Map[list[T], Case[list[int], str], Default[bytes]]` | `bytes` | `str \| bytes` |
| C6 `unknown-structural-pattern` | `Map[list[int], Case[list[T], str], Default[bytes]]` | `bytes` | `str \| bytes` |
| C7 `predicate-known-argument-mismatch` | `Map[int, Case[Equal[tuple[int, T], tuple[str, int]], str], Default[bytes]]` | `str \| bytes` | `bytes` |
| C8 `repeated-capture-unknown` | `Map[tuple[int, T], Case[tuple[Value, Value], Value], Default[bytes]]` | `bytes` | `int \| bytes` |
| C9 `nested-definite-predicate` | `Map[int, Case[Equal[Map[T, Case[T, int], Default[str]], int], bytes], Default[float]]` | `bytes \| float` | `bytes` |

For C8, equality of the repeated captures is uncertain, but a matching branch
requires the capture to be `int`. For C9, the inner exact same-symbol case is a
definite match; merely containing `T` must not make the outer predicate uncertain.

### C10: Alias in a selected alias output

```python
type Inner[A] = Map[A, Case[int, str], Default[bytes]]
type Outer[A] = Map[A, Case[int, Inner[A]], Default[float]]

class Payload:
    value: Schema[Outer[int]]
```

Observed: `Inner[int]`. Intended: `str`. This differs from the retained
`alias-in-argument` case. Owner: **slice 6, source alias expansion and generic
substitution**, tested before evaluation. Slice 7 must evaluate the expanded
expression; activate the compiler correction in slice 8.

### C11–C12: Alias cycles

```python
type First[A] = Map[A, Case[int, Second[A]], Default[A]]
type Second[A] = Map[A, Case[int, First[A]], Default[A]]
type Loop[A] = Map[A, Case[int, Loop[A]], Default[A]]
```

Probe `Schema[First[int]]` and `Schema[Loop[int]]` in separate modules (the first
contains only First/Second, the second only Loop). They currently emit
`Second[int]` and `Loop[int]`. Both must instead fail explicitly with the authored
cycle path: `First -> Second -> First` and `Loop -> Loop`.

Owner: **slice 6, source alias expansion**. Slice 7 must translate the modeled
failure into an authored `AdaptationError`; slice 8 adds `generate_module()`
failure contracts. Preserve the experiment's diagnostic intent without requiring
its helper names or exception implementation.

### C13: Literal type output inside a transformed field

```python
class Record(TypedDict):
    original: int

type Transform[T] = MapFields[
    T, Field[Key, Map[Value, Case[int, Literal["accepted"]], Default[bytes]]]
]

class Payload:
    value: Schema[Transform[Record]]
```

Observed: an adaptation failure, `field value must evaluate to a type`.
Intended: a generated `Transform_Record` with
`original: Literal["accepted"]`, referenced by `Payload.value`.

Owner: **slice 2, `lower_semantic_expression()`**, with the field value and its
nested Map output explicitly in the type-output role. Preserve the green
field-name contracts while correcting this role. Record materialization already
uses shared lowering, so this correction can affect production during slice 2;
the compiler end-to-end correction test remains assigned to slice 8 under the
roadmap's testing policy.

## Later interface contracts

Production characterization cannot demonstrate every prerequisite. Carry these
requirements into the named slices rather than adding more slice-1 xfails or
asserting internal legacy behavior:

| Slice and interface | Required contracts |
| --- | --- |
| 2, shared templates and compiler semantic lowering | Recursively retain output role through unions/applications; distinguish Literal field names from case tests, predicate operands, and type outputs. No opaque `Value` leaves. |
| 3, `evaluate()` and the shared possible-type operation | Nested deferred and union-subject outputs; normalize duplicates once; preserve modeled non-type and backend failures. |
| 4, shared model | Distinct unresolved symbols, same-symbol identity, mixed resolved/unresolved arguments, nested provenance; no compiler dependencies. |
| 5, `evaluate()` | Full three-way truth tables for `All`/`Any`/`Not`; decisive operands after unknowns; short-circuit before failing operands and propagate reachable failures; ordered unknown/unknown/default, unknown/match, and no-default cases; C1–C9. |
| 6, source alias expansion/substitution | Every source-expression variant, nested placements, generic binding before capture, explicit alias context, omitted versus explicit-Never defaults, C10–C12. |
| 7, schema adaptation and typing emission | Authored diagnostics at one modeled failure boundary, bare/qualified Never through one StaticType conversion, nested types, record references, and generic lowering; preserve compiler origins and reusable roots. |
| 8, production boundaries | Activate C1–C13 compiler correction contracts, keep retained tests green, delete the duplicate evaluator without fallback. |

Slices 2–5 are now complete at their owning interfaces. Slice 2's lowering
contracts cover C13 in `tests/unit/compiler/semantic_adapter/test_semantic_lowering.py`.
Slice 3's evaluation contracts are in `tests/unit/semantics/test_migration_spec.py`;
slice 4's data contracts are in `tests/unit/semantics/test_unresolved_types.py`.
Slice 5 consumes that model and covers C1–C9 in
`tests/unit/semantics/test_indeterminate_evaluation.py`. The observed outputs above
remain the slice-1 baseline inventory. C10–C12 still require slice 6's source alias
expansion. All C1–C13 end-to-end correction contracts remain assigned to slice 8;
the compiler schema evaluator has not cut over.

## Existing integration contracts to carry forward

These tests already protect behavior introduced by the compiler refactor. They
are retained integration requirements, not new semantic corrections or reasons
to rewrite overlay projection in slice 1.

| Existing test | Requirement for slices 7–8 |
| --- | --- |
| [`test_pipeline.py::test_schema_boundaries_resolve_in_model_fields_and_generated_stubs`](../../tests/unit/compiler/pipeline/test_pipeline.py) | Existing public schema, capture, Input, alias, and record-reference output remains green. |
| [`test_published_plan.py::test_relationship_aliases_remain_target_neutral_until_publication`](../../tests/unit/compiler/pipeline/test_published_plan.py) | Keep callable alias IR intact; publication still uses its conservative `object` fallback. |
| [`test_adaptation_origins.py`](../../tests/unit/compiler/adaptation/test_adaptation_origins.py) | Alias and record rewrites retain authored origins pointing to elements in the current module. |
| [`test_schema_plan.py::test_schema_roots_cover_records_and_scoped_methods`](../../tests/unit/overlay/test_schema_plan.py) | Retain independent reusable Schema roots and source spans, including scoped methods and records. |
| [`test_schema_plan.py::test_shared_alias_outputs_do_not_create_overlapping_schema_edits`](../../tests/unit/overlay/test_schema_plan.py) | Reusing an alias output must not collapse distinct schema-boundary identities or create overlapping edits; overlay alias fallback remains a union of outputs. |
| [`test_schema_plan.py::test_schema_roots_preserve_unspecialized_emission_failures`](../../tests/unit/overlay/test_schema_plan.py) | Unsupported reusable roots keep their modeled emission failure. |
| [`test_schema_plan.py::test_published_record_annotations_remain_opaque`](../../tests/unit/overlay/test_schema_plan.py) | Preserve the existing selected publication scope: record annotations remain opaque there, while overlays resolve valid Schema and diagnose invalid arity. Do not broaden publication scope during cutover. |
| [`test_compilation_plan.py::test_alias_projection_uses_current_alias_origins_and_preserves_source_mapping`](../../tests/unit/overlay/test_compilation_plan.py) | Projection continues to use current compiler origins for edits and source mapping. |

The overlay consumes `CompilationPlan`; it no longer calls the legacy schema
evaluator. The eventual cutover must preserve that interface and its provenance,
with overlay changes only if the compiler contract actually changes.
