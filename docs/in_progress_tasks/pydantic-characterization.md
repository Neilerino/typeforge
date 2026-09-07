# Pydantic Redesign: Runtime Contracts

Status: Slices 1–2 complete; private resolved pipeline implemented, public cutover pending

Owning task: [Pydantic integration redesign](pydantic-integration-redesign.md)

## Scope and evidence

This is the contract handoff for the replacement. The public hook is unchanged. Public behavior
is exercised through Schema, TypeAdapter, and BaseModel with actual Pydantic.
The baseline is Python 3.14.3 / Pydantic 2.13.4. Existing tests remain in place;
new characterization tests retain working behavior without enshrining discovered
bugs. One accepted correction is parked as a strict xfail; other corrections are
specified below for their owning implementation slices.

Slice 2 implements C1, C2, C3, and C8 through the private replacement hook in
`typeforge.pydantic._annotation`; its tests are in `test_replacement.py` and
`test_policy.py`. The public C1 tracer remains a strict xfail until slice 6.
Records (C4), aliases, structural captures, and runtime Input are still pending.
The new lifecycle coverage includes partial inheritance, both specialization
orders, rebuilt JSON Schemas in both modes, and JSON validation/serialization.
It also ensures a TypeVar used only in an unreachable output cannot postpone a
concrete no-match error. Unexpected schema-hook exceptions retain their identity.

`test_frontend.py` covers the per-call annotation adapter: nested authored origins,
opaque metadata, isolation across successful and failed builds, and original
identity for modeled and unexpected failures. Annotation-family handlers retain
the slice 2 behavior behind the existing `adapt_annotation` result boundary.

`test_annotation_compilation.py` verifies that parsing, evaluation, no-match, and non-type
outcomes stop before emission. Compilation uses `Result.do` for its normal stages
and a separate generic no-match recovery function; existing lifecycle and schema
hook contracts continue to exercise successful recovery and unexpected failures.

`tests/unit/semantics/test_evaluation_policy.py` covers the composed evaluator:
typed policy rejection, nested expression/context identity, explicit Never
distinction, short-circuit failure propagation, unvisited outputs, and evaluator
reuse without leaked bindings or modes. Context-bound child evaluators preserve
parent and sibling bindings after failures and during reentrant policy calls;
their shared dependencies and read-only context are covered. Speculative selected outputs, reachable
remainders, deferred bounds, and later indeterminate predicate operands retain
their evaluation mode. `test_policy.py` verifies Pydantic's definite/speculative
decision and propagation of unrelated errors. Runtime policy retains the evaluated
subject as structured issue data. The original callback is removed.

Test paths below are relative to `tests/unit/pydantic/`. A named test denotes its
full pytest function name; parameterized tests include multiple contracts.

## Retained behavior

| ID | Contract | Coverage |
| --- | --- | --- |
| R1 | Schema returns ordinary values, works as a field, and delegates leaf metadata. Resolved transformations add no Python validation callback. | Existing `test_schema.py` |
| R2 | Ordered schema-time Maps select exact/predicate cases, use defaults, distribute over unions, and reject an empty output. | Existing `test_schema.py` |
| R3 | Explicit Any mismatches int and list[Value], reaches a default or later Any case, and list[Any] captures Any. | `test_map_characterization.py::test_schema_any_cases_preserve_exact_and_structural_roles` |
| R4 | Unmatched Any without a default, explicit Default[Never], and a selected Never all reject direct schema construction. Their current conflated diagnostic is not retained. | `test_map_characterization.py::test_schema_rejects_empty_output_at_construction` |
| R5 | Repeated captures agree; a failed case does not leak a partial capture into the next case. | `test_map_characterization.py::test_structural_map_reconciles_repeated_captures`, `test_failed_structural_case_does_not_leak_capture_to_next_case` |
| R6 | Structural output templates preserve nested unions and type-valued Literals; variadic aliases bind before capture. | `test_map_characterization.py::test_nested_capture_templates_preserve_union_and_literal_types`, `test_variadic_alias_binds_each_argument_before_structural_capture` |
| R7 | Schema beneath a container preserves leaf constraints and error locations. Metadata inside and outside Schema executes once in order. | `test_map_characterization.py::test_schema_nested_beneath_container_retains_leaf_constraints`, `test_schema_preserves_metadata_inside_and_outside_the_annotation` |
| R8 | Generic aliased fields compile independently for int and bytes, coexist in a containing model, serialize correctly, and rebuild deterministically. | `test_generic_fields.py::test_generic_alias_fields_rebuild_and_keep_specializations_independent` |
| R9 | Partial inheritance substitutes known structural positions and remaining parameters; traditional Generic/TypeVar syntax works. | `test_generic_fields.py::test_partial_generic_inheritance_substitutes_nested_structural_fields`, `test_traditional_generic_field_substitutes_typevars` |
| R10 | Ordinary Schema[T] follows Pydantic's unbound, bound, constrained, and defaulted validation. Model-bound TypeVars preserve unparametrized versus explicit-bound serialization. | `test_generic_fields.py::test_ordinary_schema_typevar_preserves_pydantic_fallbacks`, `test_ordinary_model_bound_typevar_preserves_pydantic_serialization` |
| R11 | Generic field constraints, aliases, validators, serializers, and model configuration remain Pydantic-owned. Selected generic model outputs retain model identity. | `test_generic_fields.py::test_generic_field_preserves_model_configuration_and_field_middleware`, `test_generic_map_delegates_selected_model_output_to_pydantic` |
| R12 | Input chooses the first raw-input case; selected output failure does not try another case or default. | `test_input_characterization.py::test_input_selects_first_case_and_never_retries_after_output_failure` |
| R13 | Raw exact matching distinguishes bool, int, and float; no-match preserves input and stable code. Assignable predicates can intentionally match subclasses. | Existing `test_input.py`; `test_input_characterization.py::test_input_no_match_has_stable_code_and_original_input`, `test_input_predicate_assignability_can_accept_a_subclass` |
| R14 | Input supports union and Annotated type patterns and value-sensitive Literals before coercion. | `test_input_characterization.py::test_input_union_and_annotated_patterns_match_raw_types`, `test_input_literal_patterns_match_values_before_output_coercion` |
| R15 | Predicate short-circuiting skips an invalid unvisited operand; nested deferred selection observes the raw value at its validation position. | `test_input_characterization.py::test_input_predicate_short_circuit_skips_unbound_operand`, `test_nested_input_map_observes_raw_value_before_outer_output_validation` |
| R16 | Unexpected exceptions from a selected output validator propagate with identity. | `test_input_characterization.py::test_unexpected_output_validator_exception_propagates_unchanged` |
| R17 | Input supports Python/JSON, unambiguous output serialization, and overlap between input and output types without redispatching on coerced output. | Existing `test_input.py` |
| R18 | TypedDict transformations preserve requiredness, readonly information, inheritance, constraints, documentation, field error locations, and deterministic qualified references. Unsupported record families and duplicate renames fail. | Existing `test_map_fields.py`, `test_json_schema.py` |
| R19 | Invalid markers, unbound contextual references, malformed transforms, and recursive Typeforge aliases report authored errors. Ordinary recursive aliases delegate. | Existing `test_errors.py`, `test_json_schema.py` |
| R20 | Base Typeforge imports without Pydantic; explicitly importing the unavailable integration reports the optional dependency requirement. | Existing `tests/unit/runtime/test_imports.py` |

R3–R4 cover every row of the accepted Any matrix. Generic fallback equivalence
inside transformations is a correction, not implied by explicit-Any coverage.

## Corrections and implementation ownership

Observed failures were reproduced through public entry points. Do not add tests
asserting the incorrect outputs. Before implementing each correction, add its
failing contract at the named seam; keep production cutover assigned to slice 6.

| ID | Baseline observation | Required outcome | Owner / slice |
| --- | --- | --- | --- |
| C1 | Defining a generic Map field without a default fails immediately because the old evaluator emits Never for opaque T. | The generic origin exists, concrete specializations work, and unparametrized Any/no-match validation fails at the field with `typeforge_map_no_match`. | Generic lifecycle, policy, emission / 2; public cutover / 6 |
| C2 | In `Map[T, Case[int, str], Default[bytes]]`, both `T: int` and `T = int` currently yield bytes for unparametrized use. Constrained T also selects the default instead of considering its constraints. | Apply the Pydantic fallback before runtime semantic selection, preserving provenance for serialization. Default/constraints/bound precedence must match ordinary Pydantic controls. | Runtime frontend and policy / 2; aliases / 3 |
| C3 | All direct empty-output variants currently report the emitter's inability to build Never. | Report `[map_no_match]` for an unmatched Map without a default, distinguishing selected Never and Default[Never] as uninhabited outputs. Preserve the responsible expression, including nested Maps. | Shared selection outcome and integration diagnostics / 2 |
| C4 | Defining a generic `Schema[MapFields[T, ...]]` fails even when a later argument would be a TypedDict. | Permit the origin and valid concrete record specialization; invalid unparametrized Any is an unsupported record use, not invented fields. | Lifecycle / 2; records / 4 |
| C5 | A missing name inside a Typeforge alias becomes a permanent schema error before model_rebuild can resolve it. | Preserve supported forward-resolution/rebuild behavior; recursive Typeforge aliases still fail explicitly. | Runtime aliases and hook translation / 3 |
| C6 | A runtime predicate using unbound Key is swallowed as a mismatch and its default validates. | When that predicate is reached, propagate its modeled failure; never reinterpret an evaluation error as false. Preserve short-circuiting. | Shared selection and runtime diagnostics / 5 |
| C7 | Input Literal[1] matches True and validates it as 1 through Python equality. | Match literals by both type and value. True and 1, and int 1 and float 1.0, remain distinct; user confirmed this correction during slice 1. | Runtime observation/pattern policy / 5 |
| C8 | A custom output type's schema hook raising RuntimeError is wrapped as PydanticSchemaGenerationError. | Unexpected schema-hook exceptions propagate unchanged; only modeled construction failures are translated. | Error conversion / 2 |
| C9 | A parameterized runtime pattern hidden in a union bypasses the old rejection: int or list[int] accepts a list by its bare constructor. | Reject parameterized value-time patterns consistently through unions, Annotated, and aliases instead of claiming structural runtime support. | Runtime frontend / 3; Input planning / 5 |

Additional required examples for the owning slices: fallback defaults with bounds,
constraints with distinct mapped outputs, repeated generic parameter identity,
bare Any versus list[Any] through aliases, generic TypedDict reference isolation,
both specialization construction orders, combined static parameters and Input,
and selection failures beneath unions/parameterized outputs. Existing shared
semantic tests remain the oracle for three-way static comparisons; this runtime
work must not rewrite compiler unknowns into Any.

## Generic lifecycle and error phases

The public contract distinguishes declaring a generic from using an invalid
fallback schema:

| Entry point | Selected behavior |
| --- | --- |
| Direct TypeAdapter(Schema[Map[Any, Case[int, str]]]) | Construction raises PydanticSchemaGenerationError with `[map_no_match]`, Map, and Any in the authored diagnostic. |
| Define generic Payload[T] with that Map relationship | Class definition succeeds; retain the source annotation for specialization. |
| Validate Payload without arguments, where fallback Any has no matching case/default | ValidationError at the field, code `typeforge_map_no_match`, identifying Any. Do not infer T from the value. |
| Validate a matching concrete specialization | Emit the selected output schema; no generic-fallback evaluator runs per value. |
| Rebuild a specialization | Recompile from current source; prior origin/fallback state must not contaminate it. |

Unparametrized no-match JSON Schema can describe an uninhabited field using
`{"not": {}}`; generating that schema must not prevent later specialization.
The concrete schemas describe their actual output types. Do not use `{}` to
claim all values validate against an impossible field. Schema emission strategy
is private; the rejection is caused by the Map's no-match, not a blanket ban on
unparametrized models. Explicit Any arguments with an impossible Map remain
invalid concrete schema construction. Slice 2 must preserve fallback provenance
to distinguish these situations.

`test_hook_lifecycle.py::test_hook_preserves_generic_source_and_can_reject_unparametrized_use`
demonstrates the required public Pydantic capability: source arguments are
preserved for origin, concrete specialization, and rebuild; a rejecting origin
field does not block specialized schemas. It uses a local annotation hook that
records source and returns a fixed concrete schema. It is a lifecycle proof,
not a replacement evaluator or proof that C1 works today. Production is neither
patched nor mocked. Its temporary empty JSON input description is not the final
no-match JSON Schema contract above.

## Runtime Input language and resumption seam

Input denotes the raw value at the current validation position. A nested Map
selected as the output sees that raw value before output validation; an Input
inside a container's item schema sees the item. Binding static generic fallbacks
does not consume a raw value.

Supported case tests in the first replacement:

- concrete Python types, matched by exact raw type identity;
- unions of supported tests;
- Annotated around a supported test, preserving the existing underlying matching
  rule; its Pydantic validation metadata is not run to decide a branch;
- Literals, matched by exact type and value, including enum member identity/type;
- Input itself as a catch-all pattern;
- Equal, Assignable, All, Any, and Not predicates over the raw input type and
  available authored/contextual type bindings, using shared evaluation and its
  short-circuit rules.

Parameterized value-time patterns remain unsupported, including through unions,
Annotated, or aliases. Reject them explicitly during construction. Runtime
structural capture from container values is not introduced by this migration.
Unbound Value outside an available field/capture context is invalid. Static
structural Maps continue to support Value captures as documented.

Ordered selection belongs to shared semantics. Extend its existing Map-selection
owner so callers can retain the chosen case/default and bound context, or a
no-match outcome, without collapsing all paths into an output bound. Runtime
adaptation supplies on-demand test decisions from the supported raw observation
language; predicates use shared evaluation with the raw input type bound in
context. Do not put raw values or Pydantic validators in shared semantic data,
and do not put pattern-aware methods on TypeSystem. The adapter for
runtime test decisions must not choose case order, defaults, or outputs itself.

Only visited tests are evaluated. A reached modeled test failure propagates as
an error; it is not a mismatch. Shared selection returns branch identity before
emission invokes the selected output validator. Validation failure never resumes
selection at a later branch. Nested deferred results retain their own context.
Concrete API names and private plan data should be chosen when slice 5 implements
this seam, extending slice 2's evaluator and typed selection outcomes rather than
creating another ordering loop or adding callback parameters throughout traversal.

No-match uses `typeforge_map_no_match`. Other reached predicate failures use
their modeled code with a `typeforge_` prefix at validation (for example,
`typeforge_unbound_key`), preserving the authored operator and field location.
Malformed or categorically unsupported expressions still fail construction.
An invalid unvisited predicate operand stays unvisited; do not eagerly evaluate
all runtime predicates while building the dispatch plan.

## Serialization contract

Returned values have no public wrapper or hidden dispatch tag. Preserve tested
serialization where the validated output identifies an unambiguous branch, and
delegate that output's Pydantic behavior. Input/output type overlap alone must
not cause redispatch using the coerced result.

If different branches produce indistinguishable output values but require
different serializers, original branch identity cannot be recovered from those
values. This slice does not promise branch-history serialization or change the
existing heuristic into a permanent contract. A stronger overlap policy is
deferred; document this limit during public cutover. Deferred dispatch's current
`{}` validation/serialization JSON Schema is retained as an honest temporary
description, distinct from the uninhabited generic no-match field.

## Pending tracer handoff

- System/owner: Typeforge's Pydantic integration; generic schema construction,
  runtime fallback policy, and no-match emission in slice 2.
- Seam: public Schema annotation on a BaseModel field, model_validate, and rebuild.
- Test: `test_generic_fields.py::test_generic_no_default_map_specializes_and_rejects_unmatched_any`.
- Given: Map[T, Case[int, str], Case[bytes, int]] on a generic model field.
- Then: origin definition succeeds; int selects str, bytes selects int; omitted T
  falls back to Any and validation raises the field-located no-match error.
- Counterexample: no default is necessary when a case actually matches.
- Missing capability: the current hook evaluates opaque T prematurely and fails
  origin construction while trying to emit Never.
- Marker: strict xfail restricted to PydanticSchemaGenerationError; verified
  unmarked, marked, and with `--runxfail`. No production interface shells added.
- During slice 2, exercise this contract through the replacement's private
  annotation hook. Keep the public tracer pending until slice 6 switches Schema;
  then remove the marker. Do not route production through a partial replacement.

Validation commands:

```sh
rtk proxy make check src/typeforge/pydantic tests/unit/pydantic
rtk proxy .venv/bin/pytest tests/unit/pydantic/test_generic_fields.py::test_generic_no_default_map_specializes_and_rejects_unmatched_any --runxfail
rtk proxy make check
```

Slice 1 does not implement a new evaluator, generic fallback rules, no-match
schemas, literal correction, or compiler plugin. It supplies reviewable contracts
and decisions for that implementation. No dependency or lockfile changes.

Slice 1 validation result: the Pydantic suite had 72 passing cases and one intentional
strict xfail. Full make check passes pytest, Ruff lint/format, Flake8 block spacing,
mypy, and pyright. The tracer was also run with expected failures disabled and
failed during generic origin construction for the documented missing capability.

Slice 2 validation result: focused checks for Pydantic, semantics, and architecture
pass, as does full `make check` (pytest, Ruff lint/format, Flake8 block spacing,
mypy, and pyright). The private tracer passes normally; the public tracer remains
the intentional strict xfail for the slice 6 cutover. No dependency or lockfile
changes were required.
