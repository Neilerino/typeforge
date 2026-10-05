# 05 — Basic generic type functions

**What to build:** Authors construct a reusable symbolic type in a type_function without requiring compilation at runtime.

**Blocked by:** 01 — Scalar matching and Is.

**Status:** ready-for-agent

- [ ] Execute the construction body once to create an immutable template; specialization never replays application code.
- [ ] Parse the agreed restricted compiler forms without importing or executing authored code.
- [ ] Produce equivalent compiler and runtime types for supported constructions.
- [ ] Separate compiler syntax rejection from runtime validation of the constructed template.
- [ ] Support diagnostics, recursion limits, and template parameter discovery at the existing boundaries.
