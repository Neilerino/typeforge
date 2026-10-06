# 12 — Union-valued field transforms and Drop

**What to build:** Authors transform a field containing a union and drop the whole field when a matched member requests Drop.

**Blocked by:** 02 — Union selection and no-match, 10 — Field construction and immutable edits, 11 — Local generic aliases and composition.

**Status:** completed in [draft PR #12](https://github.com/Neilerino/typeforge/pull/12), stacked on slice 11.

**Derisking required:** Union selection, correlation, identity, and failure behavior were exercised across compiler, runtime, and all three checker paths in this slice.

- [x] Bare matching distributes over the field type while Is compares its complete type.
- [x] Any Drop in the concrete replacement result drops the entire field.
- [x] Keep speculative layout alternatives explicit and sound.
- [x] Compiler and runtime preserve field flags and metadata according to the accepted edit rules.

The 24 production contracts pass normally; no expected-failure marker remains.
They cover whole-field removal, exact Is, ordinary and generic field aliases,
class ancestry, inherited fields, nested containers, Any, Annotated union members,
original parameter arguments, complete capture outputs, invalid Drop positions,
uncovered members, and speculative capture effects. A recursive alias can pass
through without requiring selection expansion. All six `make check` checks passed.

A concrete Drop applies only to the replacement type position. Every member and
capture alternative evaluates before its effect is consumed. Speculative Drop
returns a typed unsupported-layout failure; D5 did not establish public support
for speculative field layouts. Correlated record unions remain slice 13.
The compiler retains its existing base-type projection for Annotated metadata;
runtime consumers retain Pydantic's metadata interpretation.

Implementation commit: `bfeb5ed84bf7e4be996f1093c4f0b26eaaebe468`.
[C4 code diagram and review receipts](../../../docs/reviews/typeforge-api/12-field-unions-drop/README.md)
remain on the separate review-artifacts branch and outside the implementation diff.
