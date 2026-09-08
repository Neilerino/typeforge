# Map slice syntax: union investigation

Status: Slice 02 investigation complete; production union fixes and semantic
decisions remain gated below. No production code changed in this slice.

Task: [Map slice syntax migration](map-slice-syntax.md).
Contract: [Authoring rules](map-slice-syntax-contract.md).
Executable evidence: [Union matrix](../../tests/unit/test_slice_union_matrix.py).
Baseline: POC `08d940a`, branch `neil/map-slice-poc`.

## Result

The exercised slice forms normalize into existing data and produce the same
results as their old Case/Default equivalents. No new union representation or
second evaluator was necessary for these experiments. Early runtime normalization
preserves union-bearing parameters and composition outside the subscription.

That establishes feasibility, not consistent union semantics across consumers.
The existing compiler has separate Schema evaluation, callable specialization,
and record materialization paths. They do not always agree with one another or
with runtime Pydantic. Renaming their inputs does not repair those differences.

The main findings are:

- Bare selectors distribute over a known union subject in shared evaluation;
  unary predicates still compare the **whole enclosing subject**. Thus bare
  `int` and `Equal[int]` are not interchangeable for union subjects.
- Bare union selectors are exact unions in static Schema evaluation, alternatives
  for runtime Input observation, and union parameter overloads in callable output.
- Resolved union equality in the compiler depends on member order; Python runtime
  union equality does not. Unresolved union provenance already handles reordering.
- Ordinary PEP 695 union aliases are expanded in static Schema evaluation but
  can remain opaque to runtime matching. Alias output validation works because
  Pydantic receives the alias rather than using it for Map selection.
- Runtime type union construction absorbs Any, while the compiler retains the
  other member paths. This can change later selection.
- A nested Map over a union-valued field distributes in Pydantic but does not
  distribute in the exercised compiler record materialization path.

These are old/new parity findings, not approved new language rules. Follow-ups
below gate portable support claims; they are not new parser restrictions.

## Static Schema and runtime matrix

Each U row has two tests: complete generated-stub equality between old and slice
spelling with the expected static field type, and runtime semantic-expression
equality with the expected Pydantic JSON schema or error. Runtime alias comparisons
use the same alias objects so fresh fixture identities cannot explain a mismatch.
The runtime column describes validation schema types, not automatic conversion
from the Map subject. U26/U27 retain deferred selection rather than selecting a
branch at schema construction.

Fixtures U16–18/U29 define `type Numbers = int | str`; U31 defines
`type Maybe[T] = T | None`. Runtime U31 is compared against Pydantic's schema for
the alias, including its reference structure. Annotated metadata in U28 is a plain
string that Pydantic does not interpret as a constraint.

| Case | Slice expression | Static Schema field | Runtime Schema |
| --- | --- | --- | --- |
| U01-subject-distribution | `Map[int \| str, int: bytes, str: float]` | `bytes \| float` | `bytes \| float` |
| U02-subject-default | `Map[int \| str, int: bytes, ...: float]` | `bytes \| float` | `bytes \| float` |
| U03-subject-order | `Map[int \| str, Assignable[object]: bytes, int: str, ...: float]` | `bytes` | `bytes` |
| U04-unmatched-member | `Map[int \| str, int: bytes]` | `bytes` | `map_no_match` |
| U05-union-selector-single-subject | `Map[int, int \| str: bytes, ...: float]` | `float` | `float` |
| U06-union-selector-union-subject | `Map[int \| str, int \| str: bytes, ...: float]` | `float` | `float` |
| U07-equal-whole-subject | `Map[int \| str, Equal[int]: bytes, ...: float]` | `float` | `float` |
| U08-equal-whole-union | `Map[int \| str, Equal[str \| int]: bytes, ...: float]` | `float` | `bytes` |
| U09-assignable-union-target | `Map[int, Assignable[int \| str]: bytes, ...: float]` | `bytes` | `bytes` |
| U10-assignable-all-subject-members | `Map[int \| str, Assignable[int]: bytes, ...: float]` | `float` | `float` |
| U11-compound-union-predicate | `Map[int, All[Assignable[int \| str], Not[Equal[str]]]: bytes, ...: float]` | `bytes` | `bytes` |
| U12-union-output | `Map[int, int: str \| None, ...: bytes]` | `str \| None` | `str \| None` |
| U13-nested-union-output | `Map[int, int: list[str \| None]]` | `list[str \| None]` | `list[str \| None]` |
| U14-map-under-union | `Map[int, int: str, ...: bytes] \| None` | `str \| None` | `str \| None` |
| U15-map-under-nested-union | `list[Map[int, int: str] \| None]` | `list[str \| None]` | `list[str \| None]` |
| U16-alias-union-subject | `Map[Numbers, int: bytes, ...: float]` | `bytes \| float` | `float` |
| U17-alias-union-selector | `Map[int, Numbers: bytes, ...: float]` | `float` | `float` |
| U18-alias-predicate-target | `Map[int, Assignable[Numbers]: bytes, ...: float]` | `bytes` | `float` |
| U19-captured-union-output | `Map[list[int \| str], list[Value]: tuple[Value \| None, ...]]` | `tuple[int \| str \| None, ...]` | `tuple[int \| str \| None, ...]` |
| U20-capture-drives-distribution | `Map[list[int \| str], list[Value]: Map[Value, int: bytes, ...: float]]` | `bytes \| float` | `bytes \| float` |
| U21-never-branch-with-valid-member | `Map[int \| str, int: Never, ...: bytes]` | `bytes` | `bytes` |
| U22-never-under-output-union | `Map[int, int: Never] \| str` | `str` | `str` |
| U23-no-match-under-output-union | `Map[int, str: bytes] \| float` | `float` | `map_no_match` |
| U24-any-union-subject | `Map[Any \| int, int: str, ...: bytes]` | `bytes \| str` | `bytes` |
| U25-any-union-output | `Map[int, int: Any \| str]` | `Any \| str` | `Any` |
| U26-input-union-bound | `Map[Input, int \| str: bytes, ...: float]` | `bytes \| float` | `object` |
| U27-distributed-deferred-bounds | `Map[int \| str, int: Map[Input, int: bytes, ...: float], ...: bytes]` | `bytes \| float` | `deferred plan + bytes` |
| U28-annotated-union-output | `Map[int, int: Annotated[str \| None, "description"]]` | `str \| None` | `str \| None` |
| U29-alias-whole-union-match | `Map[Numbers, Numbers: bytes, ...: float]` | `float` | `bytes` |
| U30-equal-same-order-union | `Map[int \| str, Equal[int \| str]: bytes, ...: float]` | `bytes` | `bytes` |
| U31-alias-union-output | `Map[int, int: Maybe[str]]` | `str \| None` | `Maybe[str]` |

U04/U23 are intentional policy differences: a reached no-match is an error in
Pydantic, including when another member of an outer union would accept a value.
Compiler policy treats no-match as Never. A selected Never is a different fact:
U21/U22 demonstrate its elimination during union construction without turning it
into a no-match failure. U08, U16/U18/U29, and U24 are divergent selections that
need follow-up; they must not be documented as cross-consumer equivalence.

## Additional consumer experiments

| Evidence | Expected and observed result | Implication |
| --- | --- | --- |
| `test_input_union_selection_validation_and_serialization` (both spellings) | `Map[Input, int \| str: int \| None, str: str, ...: bool]` accepts integer/string integer inputs; bool reaches fallback. `"true"` fails the selected output even though later branches could accept it. Validated values serialize and round-trip in the exercised cases. | Bare Input union selectors observe either member using exact leaf matching; selection cannot retry after output validation. |
| `test_input_union_predicate_operands` (Equal/Assignable, both spellings) | `Equal[Input, int \| str]` does not equal the observed type str; Assignable does accept str and bool-to-int. | Bare Input selector unions and Equal union targets differ; Assignable retains subtype behavior. |
| `test_selected_union_uses_pydantic_ambiguity_rules` (both spellings) | Selected `int \| str` preserves input `"12"` as str and serializes it as a JSON string. | Pydantic owns output union ambiguity, independently of Map branch selection. |
| `test_union_parameters_discover_substitute_and_rebuild` | Output-only T inside `list[T \| None]` remains discoverable under an outer Map union. Direct specialization agrees with canonical data. A generic alias/model specializes union selectors and outputs, validates, serializes, and rebuilds successfully. | Early normalization permits reuse of Python/Pydantic substitution; raw slices must not survive that boundary. |
| `test_source_union_selection_retains_provenance` (four pairs) | A selected `str \| bytes` is resolved; unknown T selection retains alternatives; T \| int distribution retains an indeterminate member inside unresolved union provenance. Nested Equal against str remains indeterminate. Missing fallback retains a second alternative. | Possible outputs are not a definite union, even when printed bounds agree. Existing models preserve the necessary distinctions. |
| `test_union_field_values_through_existing_materialization` (both spellings) | Pydantic maps int \| str field values to bytes \| float; compiler record alias materialization emits float. Literal-valued label unions remain literal types. | Field name/type roles survive, but nested field distribution needs a materialization follow-up. |
| `test_record_union_and_union_capture_patterns_remain_unsupported` (both spellings) | MapFields of a record union fails in both consumers; `list[Value] \| set[Value]` as a selector fails with unbound Value. | Record unions and unions of capture patterns are not supported by this experiment; separate structural branches remain the candidate spelling. |
| `test_real_checkers_observe_union_callable_contracts` (three checkers × two projections) | Published stubs and named-alias overlays agree between spellings. Checkers infer mapped union outputs and conservative fallback bounds; they reject incorrect assert_type calls. Overlays also reject an int implementation return where str \| None is required. | Generated typing syntax is portable for the exercised relationships; that does not prove its relationship agrees with Schema evaluation. |

The callable probes expose a specific semantic mismatch. All three selectors
below emit `def f(x: int | str) -> bytes` plus a `bytes | float` fallback, and
all three checkers infer bytes for `f(1)`:

```python
Map[T, int | str: bytes, ...: float]
Map[T, Equal[int | str]: bytes, ...: float]
Map[T, Assignable[int | str]: bytes, ...: float]
```

For a concrete int subject, static Schema evaluation chooses float for the first
two and bytes for the third. Overload subtype matching also cannot enforce an
exact int exclusion of bool. This is existing callable lowering behavior, not a
slice parser change. See the separate
[callable semantics cutover](../ideas/callable-map-semantics-cutover.md).

For the output test, `encode(1)` infers `str | None`, while `encode(value)` with
value: int | str infers the conservative `str | None | bytes`. Named aliases
publish as object and use possible-output bounds in overlays, preserving their
different policies. Raw inline slices were rejected by all three checkers during
this investigation. Slice 06 now projects them successfully, with
[inline and nested overlay evidence](../../tests/unit/overlay/test_inline_maps.py)
for union outputs, authored diagnostics, and the same conservative fallback.
This completes G7's inline projection work. This experiment does not
add a general finite-specialization guarantee for unbounded captures or Each/Collect.

Static `Schema[MapFields[Row, ...]]` also fails with a supported-record error in
the direct-boundary probe. Static field evidence here deliberately uses the
existing record-alias materialization path. Runtime supports the exercised
TypedDict expression. Neither result broadens record-family support.

## Slice 07 callable publication boundary

[Production publication regressions](../../tests/unit/compiler/pipeline/test_slice_publication.py)
exercise generated interfaces with mypy, Pyright, and Pyrefly at maximum arities
two and three. The consumer runs against the `.pyi` after the authored `.py` is
removed. Generated imports require no Typeforge markers. Both accepted inferred
types and an intentionally incorrect assert_type are checked, with explicit
Pyrefly configuration so its unconfigured basic preset cannot hide the failure.

The fixture preserves constants, TypedDicts, dataclasses, generic functions, and
methods alongside slice relationships. Exact/literal selectors, predicate aliases,
All/Any/Not, generic defaults, and omitted defaults use existing specialization.
An `Option[Value]: Value | None` alias composed with Each/Collect preserves captured
union outputs. Raising the configured frontier changes a three-argument call from
`tuple[object, ...]` to `tuple[int, str, bytes]`; changing consumer calls does not
change the generated stub. Published aliases remain object, while overlays retain
their output union.

These are bounded support claims. G1/G2/G4 are **constrained, not resolved**:

| Gate / form | Slice 07 boundary |
| --- | --- |
| G1: union selectors and whole-subject predicates | Existing checker-valid overload behavior remains characterized by the slice 02 checker matrix. Do not promise equality with Schema selection. Callable overload subtype matching cannot express exact exclusion of bool from int. |
| G2: reordered union equality | Union-valued outputs and captures have positive evidence. Order-independent union comparison and equivalent branch selection across consumers remain outside the supported guarantee; no equality implementation changes here. |
| G4: Any in selection | Do not rely on Any-containing subject/selector unions for portable selection. U24/U25 remain the static/runtime witnesses; this slice does not reinterpret Any or use it to replace a relationship bound. |
| Concrete union callable subject | `Map[int | str, int: bytes]` at a callable return boundary fails with MISSING_CONTROLLER. Generic-controller calls with union arguments retain the existing conservative overload result. |
| Predicate overlap and fallback | `All[Assignable[int], Not[Equal[bool]]]` gives int arguments an aggregate `str | bytes` bound and bool arguments bytes in the exercised fixture. This is existing candidate discovery behavior, not general predicate precision. |
| Verification guards | Slice 06's Assignable/isinstance precision limitation remains. Exact Equal/type guard checks pass; do not infer equivalent flow precision from publication success. |
| Unbounded structural callable outputs | `list[Value]: tuple[Value, ...]` still returns EmissionError rather than a partial interface. Finite Each/Collect evidence does not extend this boundary. |

Duplicate selectors, missing controllers, unsupported predicate controller
positions, and Each on an ordinary parameter return typed failures through both
compilation and publication. These existing rejection rules are unchanged. The
union restrictions above are documented support limits, not new parser errors.
Broader callable behavior remains with the
[callable semantics cutover](../ideas/callable-map-semantics-cutover.md).

## Slice 08 runtime integration boundary

The 85-case union matrix now uses public Map construction and canonical internal
markers directly; it no longer imports the prototype. The expected U-row results
are unchanged. This promotes generic discovery/substitution, union ambiguity,
validation/serialization, and deferred-bound evidence through production
construction, completing G7's runtime work.

The [runtime lifecycle suite](../../tests/unit/pydantic/test_runtime_pipeline.py)
and [deferred dispatch suite](../../tests/unit/pydantic/test_deferred_pipeline.py)
now author slices. They retain their prior assertions for generic fallback order,
partial inheritance, sibling specialization, rebuilds, field diagnostics,
no-match versus explicit Never, callback absence for resolved transformations,
short-circuiting, unsupported patterns, and unexpected failure propagation.
Selected output failures never run later validators. Serialization chooses from
output types without treating coerced results as fresh Input.

[Nine additional boundary cases](../../tests/unit/pydantic/test_slice_integration.py)
verify None/empty endpoint equivalence, unary None predicates, Literal string
selectors, ordinary alias roles, selected metadata, and schema-reference parity
with canonical construction. Schema wrapper references remain distinct from
ordinary alias references, as owned by Pydantic.

G1/G3/G4's migration disposition preserves existing policies with explicit
consumer restrictions. It does not resolve the broader semantic differences:

| Gate | Runtime rule retained and support boundary |
| --- | --- |
| G1 — Union selection | Bare static selectors match each distributed subject member. Unary predicates compare the whole subject. Input union selectors observe leaf alternatives; Equal still compares types and Assignable admits subtypes. U01/U05–11/U26 and dispatch tests cover these roles. Do not promise one selector has identical meaning in Schema, Input, and callable overloads. |
| G3 — Alias transparency | Static runtime matching retains ordinary alias identity. `Map[Numbers, Numbers: bytes]` can match the same alias, but `Numbers = int | str` is not a transparent union subject or Assignable target there. Input tests unwrap ordinary aliases and reject hidden parameterized patterns. Output aliases retain Pydantic metadata and references. U16/U18/U29 remain explicitly outside cross-consumer equivalence; alias transparency changes are deferred. Existing Typeforge-operator alias expansion, binding, and cycle errors remain covered by slice 05. |
| G4 — Any unions | Runtime construction absorbs Any and applies later selection to that result, as U24/U25 demonstrate. Generic defaults, constraints, bounds, and Any fallbacks remain independent of submitted values. Do not promise cross-consumer selection for Any-containing unions; the compiler's retained member paths remain different. |
| G7 — Public integration | Complete for the tested construction, substitution, overlay, publication, and runtime paths. No raw slice survives into semantic evaluation, and no additional evaluator or validation callback was needed. |

These restrictions limit support claims rather than introducing new rejection
logic. The migration preserves the existing data and evaluator behavior. G2's
compiler equality issue, G5's field distribution, and G6's unsupported structures
remain with their recorded owners; passing runtime tests does not clear them.

## Slice 09 field composition boundary

[Field integration evidence](../../tests/unit/test_slice_fields.py) compares the
same inherited TypedDict transform through published stubs and runtime Schema.
Slices and canonical branches agree on dropping password, renaming name through
a unary predicate alias, making that output optional, and selecting a readonly
`str | None` output for a scalar integer field. Literal-valued union fields stay
typing values rather than becoming field names. Plain Field makes inherited
optional/readonly inputs required and writable; this is existing operator policy.

Mypy, Pyright, and Pyrefly accept the generated record types and their union
annotations, permit writable-field mutation, and reject readonly-field mutation.
The checker fixture deliberately excludes generic callable dispatch across both
base and derived records: existing source-order overload construction places the
base first, and mypy reports `overload-cannot-match` for the derived overload.
Canonical and slice publication preserve the same ordering. This remains a
callable specialization follow-up, not a claim established by field-type checks.

Runtime record and field suites now exercise public slices, including nested
error locations, generic record specialization, record Doc metadata, leaf
constraints, shared references, and rebuilds. Compiler Annotated field metadata
remains transparent: the source parser strips it and emits the base typing type.
Pydantic retains it for validation and schema generation. Metadata preservation
claims follow these existing consumer policies.

| Gate / composition | Slice 09 disposition |
| --- | --- |
| G5 — Nested Map over union-valued Value | Explicitly constrained. The compiler's `build_record_shapes` stores field annotations as opaque NamedType values, so the existing witness emits float while runtime Schema distributes to bytes or float. Fixing structural field discovery and its downstream matching effects needs a separate compiler change; do not document this composition as cross-consumer equivalent. |
| Union output or unchanged union field | Supported by the exercised fixture in both consumers and all three checkers. This does not require rediscovering or distributing a field's input type. |
| G6 — Record unions and unions of capture patterns | Continue to fail. The public union matrix retains both-spelling errors; additional tests reject ordinary classes and parameterized dict records. No record-family or capture-pattern expansion is included. |
| Speculative field layouts | Deferred Input cannot choose a field versus Drop: both consumers reject construction with their existing typed errors. A source-normalized transform over an unresolved type parameter also fails shared evaluation rather than becoming a definite record, for both spellings. |
| Duplicate names / non-field outputs | Both boundaries reject them. Compiler failures retain the authored alias name and expression; Pydantic retains its domain error code. Diagnostic presentation changes remain with slice 10. |

G5 remains a semantic follow-up under this explicit support restriction; G6's
rejections are retained. No production evaluator, field defaults, or record model
changed in this slice.

## Supported evidence, restrictions, and follow-up gates

The following forms have useful positive evidence: explicit branches over concrete
union subjects with complete coverage, Assignable union targets for concrete
types, union outputs and nested outputs, a Map under an outer union, captured
unions within one structural pattern, and normalized generic union substitution.
Scope these claims to the tested consumer path. Branch ordering and existing
no-match/Never policy must remain explicit.

Do not promise portable union-selector semantics, transparent union alias
matching, order-independent resolved equality, Any-containing union selection,
or distributed field mapping until their gates are resolved. Do not expose union
capture patterns or record-union operands as supported. These are support limits
and unresolved decisions; this slice does not introduce rejection logic.

| Gate | Bounded follow-up / acceptance | Owner |
| --- | --- | --- |
| G1 — Union selector and predicate meaning | Settle whether the new surface preserves the observed consumer differences, rejects an unrepresentable form, or requires semantic convergence. Preserve whole-subject unary binding unless explicitly revised. Add concrete int/union/Input/Callable examples for the chosen rule. | 05, 07, 08; return semantic changes to Neil before implementation. Callable work also follows the linked cutover. |
| G2 — Resolved union equality order | Characterize compiler type-system equality for reordered/nested unions and reconcile with unresolved provenance and runtime equality without changing emitted order merely for comparison. U08 should become consistent. | Compiler semantic adapter follow-up, prerequisite for 04/07 union equality completion. |
| G3 — Union alias transparency | Decide and implement which ordinary aliases expand for runtime selection, preserving alias identity/metadata for output validation and handling cycles. U16/U18/U29 must be consistent or explicitly unsupported. | 05 with 08. |
| G4 — Any union construction | Decide a common semantic treatment or document an intentional consumer restriction; exercise selection after construction, not only equivalent permissive schemas. U24/U25 are the witnesses. | Semantic adapter follow-up in 08 with compiler verification in 07. |
| G5 — Contextual field union distribution | Reconcile compiler record materialization with shared evaluation, or explicitly constrain this composition. Include nested Value Maps, key/literal roles, and speculative field results; do not broaden record-family support. | 09. |
| G6 — Existing unsupported union structures | Keep explicit errors for record-union operands and union capture patterns. Any support expansion requires a separate design and evidence, rather than treating union alternatives as ordinary exact selectors. | 09 and diagnostics in 10; structural-pattern extension deferred. |
| G7 — Projection and constructor cutover | Carry generic discovery/substitution cases to public construction and union fallback cases to inline projection. Keep authored provenance and test wrong implementation returns. | 03, 06, 07, 08. |

Slice 03 may proceed with declarative runtime construction: its work does not
need to decide G1–G6 or modify matching. Later slices must not check off their
union-bearing acceptance criteria merely because these characterization tests
pass. When a gate changes expected behavior, replace the affected limitation
assertions with the accepted regressions and update this report as historical
evidence. Remove prototype imports at slice 11.

## Validation

Environment: Python 3.14.3, Pydantic 2.13.4, mypy 2.2.0, Pyright 1.1.411,
Pyrefly 1.1.1. Checker runs use real local executables; mypy incremental caching
is disabled for generated fixtures.

The new suite has 85 passing cases, including six real-checker projection cases.
Focused `make check tests/unit/test_slice_union_matrix.py` and full `make check`
passed (pytest, Ruff lint/format, block spacing, mypy, Pyright). Document links
and Python example parsing also passed.
Commit: pending; evidence is in the working tree.
