# 02 — Union selection and no-match

**What to build:** Ordered Map branches cover each known union member while Is always compares the complete original subject.

**Blocked by:** 01 — Scalar matching and Is.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Mixed bare and exact branches retain declaration order and the original Is subject.
- [ ] Union equality ignores order and duplicate members while emitted order remains deterministic.
- [ ] A known unmatched member fails the entire Map, including when nested under an outer union.
- [ ] Explicit Never outputs retain ordinary Python union simplification.
- [ ] Compiler, runtime, diagnostics, and checker-visible output bounds agree.
