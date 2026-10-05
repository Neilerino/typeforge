# 04 — Generic compatibility

**What to build:** Bare generic selectors follow supported Python compatibility rules with an explicit frontier.

**Blocked by:** 01 — Scalar matching and Is.

**Status:** implemented; [draft PR #4](https://github.com/Neilerino/typeforge/pull/4)

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Support the agreed variance and generic relationships in compiler and runtime.
- [x] Unsupported relationships produce an explicit result or diagnostic rather than silently mismatching.
- [x] Keep third-party models behind existing type-system seams.
- [x] Verify accepted and rejected generic relationships with the three checkers.

**Derisking evidence:** `tests/unit/test_generic_selection_contract.py` contains
22 passing contracts for mutable invariance, immutable covariance, list/tuple to
Sequence and dict to Mapping, nested containers, Any, literals, imported aliases,
exact identity, and unsupported variance. Positive and negative assignments and
generated output consumers pass with the expected outcomes in all three checkers.
Existing uncertainty and capture regressions retain their structural proofs and
failure identity. All repository checks pass, including architecture boundaries.

**Remaining frontier:** Partial generic shapes retain existing structural
reasoning and output bounds; broader unresolved variance and callable precision
remain subsequent work. Capture through compatible interfaces is ticket 07.
Unparameterized container projections, custom generic variance, general protocols,
and detailed NewType compatibility are outside this slice's resolved frontier.
