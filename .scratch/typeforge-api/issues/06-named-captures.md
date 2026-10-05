# 06 — Named captures and isolation

**What to build:** Authors bind named type captures and reuse them in the selected output with isolated matching scope.

**Blocked by:** 05 — Basic generic type functions.

**Status:** ready-for-agent

- [ ] Capture identity follows the declared symbol, including equally named independent captures.
- [ ] Repeated capture positions must agree exactly; failed attempts discard tentative bindings.
- [ ] Nested Maps reuse bound captures while enclosing parameters retain original arguments.
- [ ] Remove the replaced structural ambient Value authoring and migrate its consumers in this slice.
