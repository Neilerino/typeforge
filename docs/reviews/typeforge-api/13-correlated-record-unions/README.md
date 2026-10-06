# Slice 13 — Correlated record unions

Code commit: 70d9c53550eff5c3521edbb2e12f46c80b48b22e.

Open [architecture.html](architecture.html) in a browser. Its source badges link
to 15 verified code references at the exact implementation commit.

Public[Left | Right] transforms both TypedDict alternatives and retains their
complete field layouts. Each discriminator stays paired with its payload.
Shared RecordUnion data and memberwise evaluation preserve the original whole
T; an unsupported alternative fails the complete application.

The compiler expands concrete applications through the existing alias owner and
emits standard unions of generated TypedDicts. Runtime uses Pydantic's native
union schemas. Family adapters and scalar source mappings keep their existing
responsibilities. Slice 18 builds cross-module publication on these results;
callable precision is handled in slices 14–16.

Validation: 9/9 showcase, zero errors and warnings. All four desktop containment
measurements passed. Four endpoint screenshots were inspected in light and dark
with no visual correction rounds. The automated receipt retains visualReview:
pending; [visual-review.json](visual-review.json) records the separate perceptual
review. [delivery-receipt.json](delivery-receipt.json) binds the exact spec and HTML
bytes; [architecture.visual-check.json](architecture.visual-check.json) records
the browser evidence.

Implementation validation: 21 production contracts pass, including three checker
acceptance/rejection cases; all six make check gates pass. Runtime preserves field
constraints and flags; compiler publication keeps its existing Annotated field
base-type projection. Unresolved callable type parameters keep the existing finite
specialization path.
