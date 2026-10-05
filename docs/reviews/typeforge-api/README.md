# Typeforge API implementation stack

Each draft PR implements one approved vertical slice. Its base is the previous
stack branch; semantic blockers are recorded separately in the individual ticket.
The library is unreleased: public replacements remove superseded authoring in
the owning slice, with no compatibility layer or migration-guide work.

| Slice | User outcome | Semantic blockers | Draft PR |
|---|---|---|---|
| 01 | Scalar matching and Is | None | Pending |
| 02 | Union selection and no-match | 01 | Pending |
| 03 | Transparent aliases and explicit Any unions | 02 | Pending |
| 04 | Generic compatibility | 01 | Pending |
| 05 | Basic generic type functions | 01 | Pending |
| 06 | Named captures and isolation | 05 | Pending |
| 07 | Compatible generic interface captures | 02, 04, 06 | Pending |
| 08 | Alternative capture patterns | 02, 06 | Pending |
| 09 | Record and Fields goal API | 05 | Pending |
| 10 | Field construction and immutable edits | 09 | Pending |
| 11 | Local generic aliases and composition | 06, 09 | Pending |
| 12 | Union-valued field transforms and Drop | 02, 10, 11 | Pending |
| 13 | Correlated record unions | 02, 10 | Pending |
| 14 | Callable input contracts without fallback | 02 | Pending |
| 15 | Callable output precision | 07, 08, 14 | Pending |
| 16 | Each and Collect bounds and precision | 15 | Pending |
| 17 | Guard verification with original subjects | 02 | Pending |
| 18 | Cross-module publication and integration | 03, 11, 12, 13, 15 | Pending |

Every slice includes its relevant production behavior, tests, diagnostics, and
public documentation. Every PR carries a C4 code diagram with pinned source
links explaining the current change, its existing owners, and future extensions.

Union slices require explicit derisking; removing compatibility work does not
remove those semantic or integration checks.
