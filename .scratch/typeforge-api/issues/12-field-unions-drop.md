# 12 — Union-valued field transforms and Drop

**What to build:** Authors transform a field containing a union and drop the whole field when a matched member requests Drop.

**Blocked by:** 02 — Union selection and no-match, 10 — Field construction and immutable edits, 11 — Local generic aliases and composition.

**Status:** ready-for-agent

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [ ] Bare matching distributes over the field type while Is compares its complete type.
- [ ] Any Drop in the concrete replacement result drops the entire field.
- [ ] Keep speculative layout alternatives explicit and sound.
- [ ] Compiler and runtime preserve field flags and metadata according to the accepted edit rules.
