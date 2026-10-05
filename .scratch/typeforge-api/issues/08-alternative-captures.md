# 08 — Alternative capture patterns

**What to build:** Authors match alternative patterns and receive a union of complete correlated outputs.

**Blocked by:** 02 — Union selection and no-match, 06 — Named captures and isolation.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Evaluate each matching alternative with its own capture environment.
- [ ] Union complete instantiated outputs, preserving correlations within each alternative.
- [ ] An output using an unbound capture fails and cannot recover through fallback.
- [ ] Cover compiler, runtime, failure propagation, and standard checker projections.
