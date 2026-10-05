# 15 — Callable output precision

**What to build:** Consumers see precise generic mapped outputs where portable typing represents the dependency and sound bounds elsewhere.

**Blocked by:** 07 — Compatible generic interface captures, 08 — Alternative capture patterns, 14 — Callable input contracts without fallback.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Preserve supported captures and complete correlated outputs in callable return types.
- [ ] Publish useful output bounds for unresolved cases without claiming dependent verification.
- [ ] The three checkers agree on the accepted calls, failures, and precision frontier.
- [ ] Implementation verification stays within supported generated obligations.
