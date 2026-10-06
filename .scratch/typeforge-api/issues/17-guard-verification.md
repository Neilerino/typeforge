# 17 — Guard verification with original subjects

**What to build:** Authors verify supported guarded implementations while whole-type selectors retain the original generic subject.

**Blocked by:** 02 — Union selection and no-match.

**Status:** complete — [draft PR #17](https://github.com/Neilerino/typeforge/pull/17)

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Keep narrowed runtime values distinct from their original static subjects.
- [x] Generate the accepted bool and original-union obligations for recognized control flow.
- [x] Delegate expression checking to ordinary checkers and use documented bounds when flow is unsupported.
- [x] Report mismatches at authored return sites without introducing a Python inference engine.

Evidence: all six repository gates pass. The 25 normal public guard contracts cover native checking in mypy, Pyright, and Pyrefly, bool bounds, original union subjects, compatible implementations, and local ancestry. Existing flow and overlay suites retain authored return mapping and aggregate checks for unsupported flow.
