# 04 — Generic compatibility

**What to build:** Bare generic selectors follow supported Python compatibility rules with an explicit frontier.

**Blocked by:** 01 — Scalar matching and Is.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Support the agreed variance and generic relationships in compiler and runtime.
- [ ] Unsupported relationships produce an explicit result or diagnostic rather than silently mismatching.
- [ ] Keep third-party models behind existing type-system seams.
- [ ] Verify accepted and rejected generic relationships with the three checkers.
