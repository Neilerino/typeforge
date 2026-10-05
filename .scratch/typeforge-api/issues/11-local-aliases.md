# 11 — Local generic aliases and composition

**What to build:** Authors split a type_function into local generic aliases and compose reusable type functions.

**Blocked by:** 06 — Named captures and isolation, 09 — Record and Fields goal API.

**Status:** completed — [draft PR #11](https://github.com/Neilerino/typeforge/pull/11)

- [x] Respect local generic scope and keep nested parameters unbound until specialization.
- [x] Allow the agreed alias and type-function composition forms in source and runtime templates.
- [x] Preserve identities and authored origins and reject unsupported cycles or forms.
- [x] Emit standard interfaces for composed record and mapped results.

Validation: all six repository checks pass. The 33 production contracts cover
compiler/runtime parity, parameter shadowing, callee globals, capture identity,
composed record fields, typed failures, construction/rebuild behavior, and all
three checker consumers. Local aliases use ordinary unconstrained parameters
without defaults; compiler applications require explicit arguments. Runtime
retains native bare-alias behavior.

[C4 code diagram and evidence](../../../docs/reviews/typeforge-api/11-local-aliases/README.md)
live on the separate review-artifacts branch.
