# 02 — Union selection and no-match

**What to build:** Ordered Map branches cover each known union member while Is always compares the complete original subject.

**Blocked by:** 01 — Scalar matching and Is.

**Status:** implemented; draft PR pending

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Mixed bare and exact branches retain declaration order and the original Is subject.
- [x] Union equality ignores order and duplicate members while emitted order remains deterministic.
- [x] A known unmatched member fails the entire Map, including when nested under an outer union.
- [x] Explicit Never outputs retain ordinary Python union simplification.
- [x] Compiler, runtime, diagnostics, and checker-visible output bounds agree.

**Derisking evidence:** `tests/unit/test_union_selection_contract.py` covers both
production consumers, authored no-match diagnostics, unselected output
short-circuiting, recursive exact union comparison, and positive/negative stub
consumers in mypy, Pyright, and Pyrefly. The existing union matrix and semantic
policy tests now enforce rejection rather than silently dropping uncovered
members. All repository checks pass.

**Remaining boundaries:** Ordinary runtime alias expansion and explicit Any
union preservation belong to ticket 03; callable input and output contracts
belong to tickets 14–15. Inline output bounds do not establish accepted inputs.
