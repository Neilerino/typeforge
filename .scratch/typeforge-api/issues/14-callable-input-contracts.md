# 14 — Callable input contracts without fallback

**What to build:** A callable with a Map that has no default accepts only its covered input domain.

**Blocked by:** 02 — Union selection and no-match.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Project covered inputs into sound portable signatures.
- [ ] Require a bound, explicit specialization, or fallback when coverage cannot be represented.
- [ ] Do not publish an unrestricted callable fallback that admits known uncovered members.
- [ ] Keep ordinary inference with the three checkers and preserve authored diagnostics.
