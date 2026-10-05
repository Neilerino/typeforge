# 08 — Alternative capture patterns

**What to build:** Authors match alternative patterns and receive a union of complete correlated outputs.

**Blocked by:** 02 — Union selection and no-match, 06 — Named captures and isolation.

**Status:** complete

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Evaluate each matching alternative with its own capture environment.
- [x] Union complete instantiated outputs, preserving correlations within each alternative.
- [x] An output using an unbound capture fails and cannot recover through fallback.
- [x] Cover compiler, runtime, failure propagation, and standard checker projections.

**Validation:** All six `make check` checks pass. Twenty-six production contracts
cover overlapping and nested alternatives, complete union outputs, missing
bindings, alias expansion, original generic arguments, ordered branches, and
mypy/pyright/pyrefly consumers. Two semantic regressions prove failures propagate
after an earlier successful alternative. Two previously unsupported normalization
characterizations now pass as positive regressions. No expected-failure markers
remain in this slice.

**Remaining frontiers:** Opaque generic declarations retain conservative bounds.
Callable input/output precision remains in slices 14–16; correlated records remain
slice 13. Runtime Input keeps its existing observation frontier and does not infer
static generic capture arguments from values.
