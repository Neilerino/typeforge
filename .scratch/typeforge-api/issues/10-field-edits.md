# 10 — Field construction and immutable edits

**What to build:** Authors construct fields with keyword data and edit existing fields without losing unrelated information.

**Blocked by:** 09 — Record and Fields goal API.

**Status:** ready-for-agent

- [ ] Require name and type; default required to true and readonly to false.
- [ ] Immutable edits preserve unedited values and enforce the agreed metadata replacement and wrapping rules.
- [ ] Reject invalid names, modifiers, collisions, and Drop in unsupported positions.
- [ ] Remove replaced field constructors and migrate callers in this slice.
- [ ] Verify generated TypedDict interfaces and runtime schemas.
