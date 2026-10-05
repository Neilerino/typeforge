# Generic selector compatibility — C4 code view

Open [the interactive diagram](architecture.html) after downloading the HTML.
[The light preview](architecture.visual-check.1440x900.light.png) is also readable
directly in GitHub. Source badges link to the implementation at commit
`4fee895381e376fbce6f3d9e25e7e7cae2c29eb0`.

The main path follows Map evaluation into a resolved fixed selector, the existing
TypeSystem seam, and the new backend-neutral compatibility policy. The adapters
normalize native origins into GenericType facts. Source lowering retains import
identity separately from the spelling used in generated declarations.

The shared rule supports mutable invariance, the supported immutable covariance,
list/tuple to Sequence, and dict to Mapping. Unknown variance produces a typed
failure rather than choosing a fallback. Exact Is matching is unchanged. Capture
and partial shape matching retain existing structural proofs; interface capture
and broader unresolved callable variance are future slices.

The unlabeled evaluator-to-matcher edge is a direct call; its action is already
expressed by both endpoint names. Tags identify existing owners, changes, and
future work in the specification and node details.

Acceptance evidence is kept separately:

- [Delivery receipt](delivery.json): pinned source evidence, specification and HTML
  SHA-256 values, and all nine showcase checks with zero errors or warnings.
- [Browser receipt](architecture.visual-check.json): containment and readability
  at 1440×900, 1600×1000, 1920×1080, and 2048×1320, plus light/dark endpoint captures.
- [Visual review](review.json): image review of all four captured screenshots.
