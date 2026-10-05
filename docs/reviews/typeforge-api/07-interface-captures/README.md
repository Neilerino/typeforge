# Slice 07 — Compatible Sequence captures

The C4 code diagram follows an author's Sequence capture through both frontends,
shared projection, ordered evaluation, and native output emission. Source badges
link to code snapshot `7e0f657505f42bdd839258bdea282785c81c804f`.

Open [the interactive HTML](architecture.html) after downloading it from GitHub,
or view [the light image preview](architecture.visual-check.1440x900.light.png).
[The contact sheet](architecture.visual-check.html) contains all four captures.

The changed projection reuses one finite Sequence family relation for list,
tuple, and Sequence. Adapters retain native origin identity and tuple-marker
normalization; shared matching preserves actual element types and unresolved
provenance. Existing bindings, data, and checker emission are contextual nodes.
The future node marks alternative captures and callable precision as later work.

All six repository checks pass. Twenty-five compiler/runtime/checker contracts
and two failure-propagation regressions pass without expected-failure markers.

Delivery proves 9/9 showcase checks, zero errors or warnings, and 18 verified
source references. Browser evidence passes at 1440×900, 1600×1000, 1920×1080,
and 2048×1320. All four endpoint light/dark screenshots were actually inspected;
perceptual review passes with zero visual correction rounds.

- Specification SHA-256: `5d6c0fb128ad5a0439f416a296a58af5e152e35e673c3b7bd4249de3a610107d`
- HTML SHA-256: `7dc68dadd6709dc675f683df65ac66c221baf2d277c930dbd7fb650f63f226e1` (723,447 bytes)
- [Atomic delivery receipt](delivery.json)
- [Automated browser evidence](architecture.visual-check.json)
- [Separate perceptual review](review.json)

These artifacts live on the review branch and are excluded from implementation
PR diffs.
