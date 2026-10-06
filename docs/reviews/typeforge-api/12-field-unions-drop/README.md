# 12 — Union-valued field transforms and Drop

This C4 level 4/code diagram follows a union-valued TypedDict field through both
production consumers and the shared replacement evaluator.

Open [the standalone diagram](architecture.html), or inspect the
[desktop screenshots](architecture.visual-check.html). Source badges link to
13 verified references at commit `bfeb5ed84bf7e4be996f1093c4f0b26eaaebe468`.

The compiler retains native field structure, expands selection aliases through
its existing owner, and passes parsed class ancestry to field lowering. Runtime
matching reuses the frontend's alias binder while retaining original annotations.
Shared evaluation consumes concrete Drop only in the replacement type position;
uncovered members, unbound captures, and speculative layout effects remain errors.
The existing TypedDict and Pydantic output owners emit the result.

Record unions (13) and cross-module publication (18) remain later slices. The
compiler retains its existing base-type projection for Annotated metadata;
Pydantic interprets runtime constraints.

Validation: `make check` passed all six repository checks. The 24 field-union
production contracts are ordinary passing regressions, including all three
checkers. No expected-failure marker remains in this slice.

Diagram type: architecture. Deterministic delivery passed 9/9 showcase checks with
zero errors and warnings. Automated browser evidence passed at 1440×900,
1600×1000, 1920×1080, and 2048×1320. The four light/dark endpoint screenshots were
inspected separately; perceptual visual review passed after one spacing correction.
The automatic receipt's `visualReview: pending` remains unchanged.

Specification SHA-256: `08ee01d8edf347f92470d9194f2a10301494c26fce619791decde805e95c2ecf` (8258 bytes).
Artifact SHA-256: `cadb9e289193174892a295b430488c41affeab6e85f83249c0a833094520058d` (721093 bytes).

Receipts: [delivery](delivery-receipt.json),
[automated browser](architecture.visual-check.json), and
[separate visual review](manual-visual-review.json).
