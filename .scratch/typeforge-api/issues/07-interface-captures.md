# 07 — Compatible generic interface captures

**What to build:** Authors capture elements through supported compatible interfaces rather than only identical generic origins.

**Blocked by:** 02 — Union selection and no-match, 04 — Generic compatibility, 06 — Named captures and isolation.

**Status:** complete

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Support the agreed list and tuple Sequence relationships.
- [x] Heterogeneous tuple capture produces the agreed element union.
- [x] Retain the documented compatibility frontier and sound checker projections.
- [x] Compiler and runtime preserve captures through the selected complete output.

**Validation:** All six `make check` checks pass. Twenty-five production contracts
cover runtime/compiler outputs and mypy, pyright, and pyrefly consumers; two shared
semantic regressions prove modeled failures retain identity and unexpected
adapter exceptions propagate. No expected-failure markers remain in this slice.

**Remaining frontiers:** Alternative capture patterns belong to slice 08;
callable input/output precision belongs to slices 14–16. Compatible captures
support list, tuple, and Sequence origins. Unknown generic origins produce typed
diagnostics; this slice does not implement open generic inheritance.
