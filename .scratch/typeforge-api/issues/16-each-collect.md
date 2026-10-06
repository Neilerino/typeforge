# 16 — Each and Collect bounds and precision

**What to build:** Consumers receive precise supported Each/Collect results and honest aggregate bounds beyond specialization.

**Blocked by:** 15 — Callable output precision.

**Status:** complete — [draft PR #16](https://github.com/Neilerino/typeforge/pull/16)

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Retain finite arity as an explicit frontier rather than claiming open-ended precision.
- [x] Use the agreed conservative union fallback when concrete inputs cannot be inferred.
- [x] Preserve input contracts, generic identities, and deterministic interfaces.
- [x] Verify supported and beyond-frontier calls with all three checkers.

Evidence: all six repository gates pass. The 36 normal Each/Collect contracts cover all three checkers, runtime no-match behavior, independent captures, complete alternatives, native constraints, and body checking. Editor/proxy regressions expose the conservative generic output bound.
