# Named captures — C4 code view

Download and open [the interactive HTML](architecture.html), or read
[the GitHub preview](architecture.visual-check.1440x900.light.png). Source badges
link to implementation commit `130a02201fedb9f0e727a143b788633519002d5b`.

The main path starts with an explicitly declared Capture token. Native typing
construction retains the token inside the immutable type-function template.
Runtime adaptation lowers it to a scoped CaptureReference; source interpretation
uses the declaration span to create the same kind of TypeSymbol without executing
the application. Both frontends use the existing shared matcher and Evaluator.

Labels help display and diagnostics; declarations establish identity. Matching
extends immutable tentative bindings. Repeated positions must agree exactly,
failed attempts discard their bindings, and nested Maps read an already bound
token rather than capture again. A selected output requiring an unbound token
fails instead of trying a fallback. Enclosing type parameters retain the original
supplied arguments.

The lower compiler branch preserves declaration identity in CaptureType for the
existing finite Each/Collect specialization. Only the selected branch's declared
token is replaced. Existing checker calls and proxy hovers keep their precision;
multiple independent captures per callable branch remain a diagnosed frontier
until slice 15. Generic type-function declarations may expose an object bound
when an unknown subject cannot reveal fresh arguments. Concrete applications
still evaluate the retained template; known bindings preserve narrower bounds.

Structural Value authoring, its shared context slot, and unnamed compiler IR are
removed. Field Value remains until the Record/Fields cutover in slice 09.
Compatible interface captures, alternative patterns, and broader callable
precision follow in slices 07, 08, and 15.

Acceptance evidence is separated:

- [Delivery receipt](delivery.json): 19 pinned source references, specification/HTML
  hashes, all nine showcase checks, and zero errors or warnings.
- [Browser receipt](architecture.visual-check.json): containment and readability
  at four desktop sizes plus endpoint light/dark captures.
- [Visual review](review.json): inspection of all four endpoint screenshots.
