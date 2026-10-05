# 01 — Scalar matching and Is

**What to build:** Authors select scalar types by Python assignment compatibility, or use Is for an exact whole-type comparison.

**Blocked by:** None — can start immediately.

**Status:** implemented — draft PR [#1](https://github.com/Neilerino/typeforge/pull/1)

- [x] Compiler Schema and runtime Schema agree on bool/int, declared inheritance, numeric widening, Any, and exact Is selection.
- [x] Is takes one argument; malformed and removed public selectors receive authored diagnostics.
- [x] Remove public Equal, Assignable, All, Any, and Not and migrate repository callers in the same slice.
- [x] Generated standard interfaces are accepted by mypy, Pyright, and Pyrefly and reject incompatible consumers.
