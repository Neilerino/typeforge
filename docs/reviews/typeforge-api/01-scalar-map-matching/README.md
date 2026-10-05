# Scalar matching review diagram

Open `architecture.html` locally for the interactive code view. The screenshots
provide a preview in GitHub. Source badges link to the implementation commit.

Bare selectors now match by Python compatibility, while Is lowers to existing
exact comparison data. Runtime construction and source adaptation feed the
existing shared evaluator. The changed compatibility helper calls either type
adapter through the existing TypeSystem seam. Selected outputs still use the
existing stub and Pydantic emitters. Dashed future work is outside this PR.

Validation: 9/9 showcase, zero errors or warnings. Chrome containment and
readability pass at 1440×900, 1600×1000, 1920×1080, and 2048×1320. Light and dark
endpoint screenshots were visually reviewed after one composition correction.
SHA bindings and the separate artifact, browser, and visual-review receipts are
included alongside the diagram.
