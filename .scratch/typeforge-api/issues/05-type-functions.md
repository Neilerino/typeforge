# 05 — Basic generic type functions

**What to build:** Authors construct a reusable symbolic type in a type_function without requiring compilation at runtime.

**Blocked by:** 01 — Scalar matching and Is.

**Status:** implemented; [draft PR #5](https://github.com/Neilerino/typeforge/pull/5)

- [x] Execute the construction body once to create an immutable template; specialization never replays application code.
- [x] Parse the agreed restricted compiler forms without importing or executing authored code.
- [x] Produce equivalent compiler and runtime types for supported constructions.
- [x] Separate compiler syntax rejection from runtime validation of the constructed template.
- [x] Support diagnostics, recursion limits, and template parameter discovery at the existing boundaries.

**Evidence:** 33 production contracts cover once-only construction without source,
composition, precise plain annotations, generic model specialization and rebuilds,
metadata, parameter identity, invalid templates and symbolic truthiness, compiler
syntax rejection and cycles, and positive/negative consumers in all three checkers.
The optional-dependency import probe includes type-function construction.

**Remaining frontier:** The basic compiler supports one final return with an
optional docstring, no value parameters or other decorators, and unconstrained
ordinary type parameters without defaults. Capture declarations, local aliases,
and record comprehensions extend the body language in tickets 06, 11, and 09.
Runtime extra construction code does not require matching compiler acceptance.
