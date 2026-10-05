# 06 — Named captures and isolation

**What to build:** Authors bind named type captures and reuse them in the selected output with isolated matching scope.

**Blocked by:** 05 — Basic generic type functions.

**Status:** complete

- [x] Capture identity follows the declared symbol, including equally named independent captures.
- [x] Repeated capture positions must agree exactly; failed attempts discard tentative bindings.
- [x] Nested Maps reuse bound captures while enclosing parameters retain original arguments.
- [x] Remove the replaced structural ambient Value authoring and migrate its consumers in this slice.

All 37 production contracts pass, including compiler/runtime parity and all three
checkers consuming generated concrete annotations. All repository checks pass.
Unknown generic capture declarations retain an object bound while concrete
specializations stay precise. Already bound captures remain references in nested
generic Maps. Module capture values retain standard object annotations in stubs.

Structural Value authoring, its shared semantic pattern/context slot, and the
unnamed compiler IR have been removed. Existing finite Each/Collect integrations
retain one-capture branch precision through declared symbol identity. Multiple
independent callable captures are diagnosed until slice 15 extends that frontier.
Alternative/interface captures remain slices 08/07; field Value remains until 09.
