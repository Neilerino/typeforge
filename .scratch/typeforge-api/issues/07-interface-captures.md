# 07 — Compatible generic interface captures

**What to build:** Authors capture elements through supported compatible interfaces rather than only identical generic origins.

**Blocked by:** 02 — Union selection and no-match, 04 — Generic compatibility, 06 — Named captures and isolation.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Support the agreed list and tuple Sequence relationships.
- [ ] Heterogeneous tuple capture produces the agreed element union.
- [ ] Retain the documented compatibility frontier and sound checker projections.
- [ ] Compiler and runtime preserve captures through the selected complete output.
