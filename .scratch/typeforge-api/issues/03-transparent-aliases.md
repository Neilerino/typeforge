# 03 — Transparent aliases and explicit Any unions

**What to build:** Ordinary aliases select as their expanded types and explicit Any union members survive exact comparisons.

**Blocked by:** 02 — Union selection and no-match.

**Status:** implemented — [draft PR #3](https://github.com/Neilerino/typeforge/pull/3)

**Derisking required:** Verify union selection, correlation, identity, and failure behavior across the relevant compiler, runtime, and checker paths during this slice.

- [x] Expand aliases consistently in subjects and selectors without losing output metadata or parameter identity.
- [x] Preserve explicit Any members through unions, nested Maps, and aliases.
- [x] Report cycles at the owning boundary and preserve authored provenance.
- [x] Compiler and runtime agree on the accepted alias and Any examples.

**Derisking evidence:** `tests/unit/test_alias_selection_contract.py` contains 24
passing contracts, including compiler/runtime parity, recursive selection
failures, finite repeated applications, NewType identity preservation, output
metadata, and positive/negative generated-stub consumers in all three checkers.
The existing Pydantic alias suite preserves recursive outputs, definition
references, constrained TypeVar serialization, and specialization independence.
The union matrix now records transparent aliases and explicit Any outputs as
passing behavior. All repository checks pass.

**Remaining boundaries:** Generic variance/interface compatibility is ticket 04.
Ordinary recursive output aliases continue to delegate to Pydantic at runtime;
the source compiler retains its existing cycle diagnostic. Detailed NewType
compatibility and identical checker display spellings are outside this slice.
