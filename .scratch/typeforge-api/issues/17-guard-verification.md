# 17 — Guard verification with original subjects

**What to build:** Authors verify supported guarded implementations while whole-type selectors retain the original generic subject.

**Blocked by:** 02 — Union selection and no-match.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Keep narrowed runtime values distinct from their original static subjects.
- [ ] Generate the accepted bool and original-union obligations for recognized control flow.
- [ ] Delegate expression checking to ordinary checkers and use documented bounds when flow is unsupported.
- [ ] Report mismatches at authored return sites without introducing a Python inference engine.
