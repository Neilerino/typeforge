# 13 — Correlated record unions

**What to build:** Authors transform every TypedDict alternative independently and retain the correlated record union.

**Blocked by:** 02 — Union selection and no-match, 10 — Field construction and immutable edits.

**Status:** implemented in draft [PR #13](https://github.com/Neilerino/typeforge/pull/13),
on neil/13-correlated-record-unions, based on slice 12.

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Preserve each alternative’s complete field layout and type correlations.
- [x] An unsupported alternative fails the entire transformation.
- [x] Generated interfaces and runtime schemas preserve the accepted union of complete records.
- [x] Diagnostics identify the authored unsupported operand.

The first production tracer constructs Public[Left | Right], drops each record's
secret field, accepts both complete outputs, and rejects crossed discriminator,
payload, and layout combinations. Its compiler contract expects a union of the
existing Public_Left and Public_Right generated declarations.

The production contract now contains 21 passing cases. The first tracer's real
unsupported_record failure was exposed with --runxfail, followed by strict XPASS
and removal of its pending marker. Shared RecordUnion retains complete shapes and
clears construction metadata. Runtime uses native union schemas. Compiler
applications reuse ordinary alias expansion and original whole arguments,
preserve record-alternative identity, and allocate deterministic output names.
Constant record operands and callable specializations retain every complete
output alternative.

Derisking covered aliases, composition, reversed and duplicate members, overlapping
field layouts, field constraints and modifiers, outer metadata, unsupported
members and Never, original generic arguments, generic model rebuilds, naming
collisions, and mypy/Pyright/Pyrefly acceptance and rejection. Compiler field
metadata retains its existing published base-type projection.

All six repository gates pass. Code commit:
70d9c53550eff5c3521edbb2e12f46c80b48b22e. The C4 code diagram verifies 15
references at that exact commit and passes 9/9 showcase checks, all four desktop
browser measurements, and separate inspection of the four light/dark screenshots.
See [the review artifacts](../../../docs/reviews/typeforge-api/13-correlated-record-unions/README.md).
