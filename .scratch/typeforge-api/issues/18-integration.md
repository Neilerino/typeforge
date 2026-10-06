# 18 — Cross-module publication and integration

**What to build:** Libraries publish complete reusable interfaces and consumers use them through editors, checkers, and runtime integrations.

**Blocked by:** 03 — Transparent aliases and explicit Any unions, 11 — Local generic aliases and composition, 12 — Union-valued field transforms and Drop, 13 — Correlated record unions, 15 — Callable output precision.

**Status:** complete — [draft PR #18](https://github.com/Neilerino/typeforge/pull/18)

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Preserve the complete public module interface, deterministic generated names, and authored origins.
- [x] Cross-module aliases and type functions compose through the existing publication and proxy paths.
- [x] Generic Pydantic rebuilds retain independent specializations.
- [x] Verify the agreed record, union, callable, editor, and runtime examples end to end.
- [x] Remove superseded implementation within the replaced scope; no parallel legacy public API or migration guide is required.

Eight normal public integration contracts verify stub-only re-exports, imported native generic alias composition, mapped callables, discriminated record unions, deterministic publication, independent runtime model specialization and rebuild, template construction counts, field-union Drop, Pyrefly hover, authored diagnostics, and atomic failure of unsupported record alternatives.

The real red exposed module variables publishing generic fallbacks instead of concrete outputs. SourceModule now retains their names and spans; existing adaptation and record application discovery own their types. Publication merges adapted variables into the existing surface and uses native checker bounds for inline Map annotations. Complete variable roots prevent overlapping overlay edits. Inferred variables and public re-exports retain their existing owners.

Cross-module static consumers use published native aliases, overloads, and representable bounds. Native typing cannot reconstruct a conditional template from its bound; libraries export concrete aliases or callable specializations for that precision. Runtime imports retain the original symbolic templates without mandatory compilation or replay. This follows the agreed portable-checker boundary, rather than adding an application import or Python inference engine to the compiler.

Validation: all six repository gates pass. Focused integration and inline Map contracts pass normally (25 tests); no pending expected-failure markers remain for this slice. Archify passes 9/9 showcase checks; artifact-bound browser evidence and actual screenshot review pass.
