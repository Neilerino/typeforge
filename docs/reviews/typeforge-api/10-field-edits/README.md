# Slice 10 — Field construction and immutable edits

The author can construct a new field with keyword data or edit only selected
properties of an existing field:

```python
Field(name="display_name", type=str, required=False, readonly=True)
field.replace(type=bytes)
```

[Open the interactive C4 level 4 code diagram](architecture.html).
GitHub displays HTML as source; download that file and open it locally.
[Light screenshot](architecture.visual-check.1440x900.light.png) and
[dark screenshot](architecture.visual-check.1440x900.dark.png) preview it here.

## Reading the code path

The runtime factory produces immutable typing data and protects literal field
names from forward-reference resolution. The compiler parser recognizes keyword
calls and lexical field replacements without executing authored source. Both
frontends lower into FieldExpression or FieldReplacementExpression.

Shared evaluation uses the original scoped RecordField. Overrides preserve
omitted values, including optional and readonly flags. Replacing the complete
type replaces its metadata; wrapping field.type retains metadata at the nested
position. A replacement type of Drop removes the entry. Names, booleans and
collisions fail through the existing typed boundaries.

The existing compiler emitter writes standard TypedDict modifiers.
The existing Pydantic _RecordAnnotation builds native TypedDict schemas.
No new record family is introduced. A newly constructed Record clears operand
metadata; explicit outer Annotated metadata applies to the new result.

## Review and remaining scope

All six repository checks pass, including 1,495 tests. The 39 new Field edit
contracts cover runtime schemas, compiler output, metadata positions, defaults,
immutable edits, failure positions, collisions, cutover, and all three checkers.
The old Field subscription, OptionalField and ReadonlyField authoring is removed;
repository callers migrate in this slice.

Compiler modifiers currently require literal booleans. Runtime construction uses
ordinary Python to produce valid symbolic templates. Local aliases, union-valued
field edits and correlated record unions remain in slices 11–13.

## Evidence

- Source snapshot: `b3e56912772f0f1997c31e363baa89c066bffb8b` with 13 verified code references.
- [Delivery receipt](delivery-receipt.json): 9/9 showcase checks, no errors or warnings.
- [Browser receipt](architecture.visual-check.json): containment and readability
  pass at 1440×900, 1600×1000, 1920×1080 and 2048×1320.
- [Separate visual review](review.json): all four endpoint captures actually inspected
  in both themes. The automated receipt retains its independent pending visual-review
  status; it does not claim perceptual review or interactive testing.
- Specification SHA-256: `754c96a648b1a0f797981559c1d7e3b638103fa91ab7ea181929073a78a939cb`.
- Artifact SHA-256: `0cfe59f4661c00f7478ea058b5aec0b25bbc23ef7a4c5e5f8a7821e001d42e42` (718498 bytes).
- Visual correction rounds: 1; artifact layout corrections before browser review: 2.

Generated review files are published only on
`neil/typeforge-api-review-artifacts`. The implementation PR contains source,
tests and relevant product documentation.
