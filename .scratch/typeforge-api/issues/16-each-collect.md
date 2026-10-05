# 16 — Each and Collect bounds and precision

**What to build:** Consumers receive precise supported Each/Collect results and honest aggregate bounds beyond specialization.

**Blocked by:** 15 — Callable output precision.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Retain finite arity as an explicit frontier rather than claiming open-ended precision.
- [ ] Use the agreed conservative union fallback when concrete inputs cannot be inferred.
- [ ] Preserve input contracts, generic identities, and deterministic interfaces.
- [ ] Verify supported and beyond-frontier calls with all three checkers.
