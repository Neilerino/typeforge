# Transparent aliases review diagram

Open `architecture.html` locally for the interactive C4 code view. Source badges
link to the implementation commit; screenshots provide GitHub previews.

Runtime selection now exposes ordinary aliases through the existing alias binding
and cycle owner. Already expanded arguments preserve finite nested applications;
child bindings preserve parameter identity. Both frontends still feed shared Map
evaluation. The runtime union builder now retains explicit members beside Any.
Selected output aliases continue to delegate Pydantic metadata and references.
The dashed extension marks generic compatibility and named captures in later PRs.

Validation: 9/9 showcase, zero errors or warnings. Chrome containment and
readability pass at 1440×900, 1600×1000, 1920×1080, and 2048×1320. Light and dark
endpoint screenshots were visually reviewed without further composition changes.
The SHA-bound artifact, automated browser receipt, and separate perceptual review
are saved alongside the source specification.
