# 09 — Record and Fields goal API

**What to build:** Authors build a TypedDict with Record over Fields using readable field-level construction.

**Blocked by:** 05 — Basic generic type functions.

**Status:** implemented — all repository checks pass

- [x] Support the accepted type_function comprehension, field passthrough, and Drop filtering.
- [x] Preserve requiredness, readonly state, and metadata for passed-through fields.
- [x] Keep record-family adaptation separate so future Protocol support remains possible.
- [x] Remove MapFields and ambient field bindings and migrate repository consumers in the same slice.
