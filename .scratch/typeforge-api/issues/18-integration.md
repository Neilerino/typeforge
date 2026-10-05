# 18 — Cross-module publication and integration

**What to build:** Libraries publish complete reusable interfaces and consumers use them through editors, checkers, and runtime integrations.

**Blocked by:** 03 — Transparent aliases and explicit Any unions, 11 — Local generic aliases and composition, 12 — Union-valued field transforms and Drop, 13 — Correlated record unions, 15 — Callable output precision.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Preserve the complete public module interface, deterministic generated names, and authored origins.
- [ ] Cross-module aliases and type functions compose through the existing publication and proxy paths.
- [ ] Generic Pydantic rebuilds retain independent specializations.
- [ ] Verify the agreed record, union, callable, editor, and runtime examples end to end.
- [ ] Remove superseded implementation within the replaced scope; no parallel legacy public API or migration guide is required.
