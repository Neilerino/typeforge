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
different policies. Raw inline slices remain the POC's known rejection in all
three checkers; their projection belongs to slice 06. This experiment does not
add a general finite-specialization guarantee for unbounded captures or Each/Collect.

Static `Schema[MapFields[Row, ...]]` also fails with a supported-record error in
the direct-boundary probe. Static field evidence here deliberately uses the
existing record-alias materialization path. Runtime supports the exercised
TypedDict expression. Neither result broadens record-family support.

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
