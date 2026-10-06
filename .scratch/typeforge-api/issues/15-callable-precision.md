# 15 — Callable output precision

**What to build:** Consumers see precise generic mapped outputs where portable typing represents the dependency and sound bounds elsewhere.

**Blocked by:** 07 — Compatible generic interface captures, 08 — Alternative capture patterns, 14 — Callable input contracts without fallback.

**Status:** complete; [draft PR #15](https://github.com/Neilerino/typeforge/pull/15)

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Preserve supported captures and complete correlated outputs in callable return types.
- [x] Publish useful output bounds for unresolved cases without claiming dependent verification.
- [x] The three checkers agree on the accepted calls, failures, and precision frontier.
- [x] Implementation verification stays within supported generated obligations.

## Implementation progress

- Normal passing publication/overlay regressions cover whole-subject capture
  identity and authored bounds, structural element reuse, distinct declarations
  with the same label, complete alternative outputs, imported interface aliases,
  nested scalar Maps, enclosing generic names, exact-selector output bounds, and
  numeric compatibility. Mypy, Pyright, and Pyrefly check these examples.
- Generated overload inputs are intersected with authored bounds. The checker
  contracts reject inputs outside int, preserve list[object] invariance, and retain
  element precision for list[Any]. A specialized signature that covers the bound
  replaces an otherwise unreachable aggregate overload.
- Native container parameters admit subclasses without structural matching facts.
  Their returns retain the captured element and include reachable fallback outputs.
  The Numbers(list[int]) runtime witness is now a normal regression. A no-default
  captured-list callable reports UNREPRESENTABLE_COVERAGE instead of publishing an
  input contract that cannot exclude this witness. Both former pending contracts
  are resolved; their old strict xfail markers are removed.
- Reachable unbound output captures produce MISSING_CAPTURE through shared
  evaluation before output erasure. Default validation uses existing native-domain
  coverage proof; whole-subject captures still skip unreachable outputs.
- Pipeline return projections preserve original generic names and expose native
  body obligations. Newly generated generic parameters are erased to a covariant
  object or invariant Any bound when absent from the authored body scope. Native
  return diagnostics map back to authored source. This is output-bound checking,
  not arbitrary dependent verification.
- Opaque nested selectors use compiler-owned symbolic bindings through the shared
  matcher. Known positions and complete alternatives survive beside unknown
  arguments. Covariant unknowns use object; invariant unknowns use Any. Missing
  bindings and known no-match paths remain typed failures.
- A nested no-default Map can reuse an original generic bound only when the native
  coverage owner proves that entire bound covered. Partial unions, Any, and exact
  selectors do not borrow a stronger contract.
- Native repeated captures preserve homogeneous precision and retain conservative
  joins/fallbacks for heterogeneous values. Semantic repeated captures still require
  exact agreement. Native gradual Any inference remains checker-owned.
- Current checks: all six make check gates pass. Callable precision suite:
  65 normal passing cases; no expected-failure markers remain in this suite.
  Full check log: /private/tmp/typeforge-slice-15-final-publication-check.log.

Slices 16 (Each/Collect), 17 (original whole-subject guard verification), and 18
(integration) remain separate work. This slice does not claim arbitrary dependent
implementation verification.
