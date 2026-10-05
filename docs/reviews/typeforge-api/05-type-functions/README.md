# Basic type functions — C4 code view

Download and open [the interactive HTML](architecture.html), or read
[the GitHub preview](architecture.visual-check.1440x900.light.png). Source badges
link to implementation commit `20f1644c184674b69b2571ff496bba119ea511be`.

The main path starts with normal Python import, constructs a template once, then
uses Schema and the existing runtime alias binder to specialize it. The retained
TypeAliasType is immutable and carries original parameter and authored module
identity. The runtime constructor copies only parameter closure cells. Its body
can use ordinary Python construction code; later specialization never calls it.

The lower path reads compiler-supported source into Typeforge alias facts,
specializes through the existing schema boundary, and lowers into the same
Evaluator. Source interpretation never imports or executes the application. Both
paths feed existing standard typing or Pydantic emission, preserving checker
ownership of ordinary value checks.

Future captures, record construction, and local aliases extend the body language
in their own slices. They do not require replaying the original body or another
expression evaluator. The diagram's Schema edge denotes later template use,
not a call made by the construction body.

Acceptance evidence is separated:

- [Delivery receipt](delivery.json): pinned source links, specification/HTML hashes,
  all nine showcase checks, and zero errors or warnings.
- [Browser receipt](architecture.visual-check.json): successful containment and
  readability at four desktop sizes plus endpoint light/dark captures.
- [Visual review](review.json): image review of all four endpoint screenshots.
