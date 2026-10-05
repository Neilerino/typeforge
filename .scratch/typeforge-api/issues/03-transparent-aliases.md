# 03 — Transparent aliases and explicit Any unions

**What to build:** Ordinary aliases select as their expanded types and explicit Any union members survive exact comparisons.

**Blocked by:** 02 — Union selection and no-match.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Expand aliases consistently in subjects and selectors without losing output metadata or parameter identity.
- [ ] Preserve explicit Any members through unions, nested Maps, and aliases.
- [ ] Report cycles at the owning boundary and preserve authored provenance.
- [ ] Compiler and runtime agree on the accepted alias and Any examples.
