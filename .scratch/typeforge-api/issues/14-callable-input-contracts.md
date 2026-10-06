# 14 — Callable input contracts without fallback

**What to build:** A callable with a Map that has no default accepts only its covered input domain.

**Blocked by:** 02 — Union selection and no-match.

**Status:** draft PR [#14](https://github.com/Neilerino/typeforge/pull/14)

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Project covered inputs into sound portable signatures.
- [x] Require a bound, explicit specialization, or fallback when coverage cannot be represented.
- [x] Do not publish an unrestricted callable fallback that admits known uncovered members.
- [x] Keep ordinary inference with the three checkers and preserve authored diagnostics.

**Validation:** `make check` passes all six repository gates. The production contract also checks published interfaces and overlays with mypy, Pyright, and Pyrefly, plus runtime union/raw-input failures. Exact-only and structural coverage fail with authored guidance; no-default Each/Collect remains an explicit frontier for slice 16.
