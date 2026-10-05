# 13 — Correlated record unions

**What to build:** Authors transform every TypedDict alternative independently and retain the correlated record union.

**Blocked by:** 02 — Union selection and no-match, 10 — Field construction and immutable edits.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Preserve each alternative’s complete field layout and type correlations.
- [ ] An unsupported alternative fails the entire transformation.
- [ ] Generated interfaces and runtime schemas preserve the accepted union of complete records.
- [ ] Diagnostics identify the authored unsupported operand.
