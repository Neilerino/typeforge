# Slice 08 — Alternative capture patterns

The C4 code diagram follows an overlapping selector through compiler/runtime
lowering, independent match environments, complete output instantiation, and the
existing union builder. Source badges pin code snapshot
`9dc7cf872d8f4b33ac74e17f32b87edaf11c21be`.

Download and open [the interactive HTML](architecture.html), or view the
[light image preview](architecture.visual-check.1440x900.light.png).
[The contact sheet](architecture.visual-check.html) contains all four captures.

AlternativeTypePattern keeps structural alternatives distinct from ordinary type
unions. MapSelection retains each environment until Evaluator instantiates its
complete output. Existing named identity, repeated agreement, generic bounds, and
native integration nodes supply context. The future node marks callable precision
as later work. A matched unbound output fails; it never selects a fallback.

All six `make check` checks pass. Twenty-six new production contracts, two
failure-propagation regressions, and two promoted normalization characterizations
pass normally. Three checker consumers accept the correlated union and reject
mixed-pair uses. Runtime validation rejects a mixed pair too.

Atomic delivery passes 9/9 showcase checks with zero errors or warnings and 16
verified source references. Browser evidence passes at 1440×900, 1600×1000,
1920×1080, and 2048×1320. All four endpoint screenshots were actually inspected;
separate perceptual review passes with zero visual correction rounds.

- Specification SHA-256: `f65cb29695ec3fc92f676667766d0315124f98a67c51b6329df42590ddfa8c79`
- HTML SHA-256: `caa21ac3b3ab9c10cf856c1793af50a43e86871ad086291d22fc9fa9ea862437` (723,059 bytes)
- [Delivery receipt](delivery.json)
- [Automated browser evidence](architecture.visual-check.json)
- [Separate perceptual review](review.json)

Artifacts are maintained on the review branch and excluded from implementation
PR diffs.
