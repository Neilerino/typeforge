# Slice 11 — Local aliases and composition

Authors can factor a type function into local generic aliases, use a composed record as a Fields operand, and return a composed record template directly.

[Open the C4 code diagram source](architecture.json) or download [the interactive HTML](architecture.html). GitHub displays the HTML source; open the downloaded file in a browser for the interactive viewer.

The highlighted compiler path owns lexical source facts, expands local helpers before outer specialization, and expands composed templates before record classification. The runtime path reuses native Python alias identities and the existing Schema frontend. Both reach the existing evaluator and family output adapters.

Review the parameter qualification and alias substitution together: a callee's global alias must remain distinct from a caller's equally named generic parameter. Existing expansion remains the owner of arity and cycle failures. The source model retains private alias spans and capture identities; private local aliases do not emit public names.

The contract file covers scalar maps, generic shadowing, forward references, distinct local scopes, composed records, field flags, capture isolation, typed failures, construction/rebuild behavior, and consumers checked by mypy, pyright, and pyrefly. All six repository checks passed for the pinned implementation.

The initial compiler frontier supports unconstrained ordinary alias parameters without defaults and requires explicit arguments. Runtime retains Python's existing native bare-alias policy. The finite visible-TypedDict materialization frontier still applies. Slice 12 derisks union-valued field replacement; slice 18 covers cross-module composition.

Evidence is pinned to implementation commit `e4ff9d411de94b25dd3d484a1f7870b0e6c5c9d5`, with 10 verified code references.

- Diagram type: architecture, C4 level 4.
- Validation: 9/9 showcase checks; 0 errors and 0 warnings.
- Specification SHA-256: `8a67c83a8939244a47f83b403d67118fefd69289f8d1658135783c60d2592aed`.
- Artifact SHA-256: `5f36eb3173c547ad2471d9d1e7b3786ee4393363af122e15d41c252097a0a6f0` (715955 bytes).
- Browser evidence: passed at all four desktop sizes, with endpoint screenshots in both themes.
- Visual review: passed after inspecting all four original-resolution screenshots.
- Corrections: one diagnosed label-placement repair; zero visual correction rounds.

[Delivery receipt](delivery-receipt.json), [automated browser evidence](architecture.visual-check.json), [contact sheet](architecture.visual-check.html), and [separate visual review](review.json).

The automated receipt intentionally retains `visualReview: pending`; the screenshot review is recorded separately. Search, focus, source passports, and exports were not exercised. Review artifacts stay on `neil/typeforge-api-review-artifacts` and are excluded from the implementation PR.
