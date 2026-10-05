# 10 — Field construction and immutable edits

**What to build:** Authors construct fields with keyword data and edit existing fields without losing unrelated information.

**Blocked by:** 09 — Record and Fields goal API.

**Status:** implemented — all six checks pass; 1,495 tests, including 39 new contracts

- [x] Require name and type; default required to true and readonly to false.
- [x] Immutable edits preserve unedited values and enforce the agreed metadata replacement and wrapping rules.
- [x] Reject invalid names, modifiers, collisions, and Drop in unsupported positions.
- [x] Remove replaced field constructors and migrate callers in this slice.
- [x] Verify generated TypedDict interfaces and runtime schemas.
