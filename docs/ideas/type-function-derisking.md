# Approved API derisking

Date: 2026-09-30. Scope: the [approved initial API](map-selection-decisions.md),
following the [earlier record-comprehension POC](record-comprehension-poc.md).

Verdict: the exercised syntax, named captures, record transforms, concrete
checker projections, and Pydantic lifecycle are feasible. The runtime body gate
is resolved by the [agreed construction boundary](map-selection-decisions.md#runtime-construction-and-compiler-support):
compilation stays optional, and compiler source restrictions are distinct from
runtime template validity. Existing compatibility and callable projection owners
also need substantive changes; AST normalization is insufficient.
Production implementation has not started.

## Evidence and limits

The separate throwaway experiment passes 121 assertions, including 57 concrete
applications lowered independently from source AST and runtime typing objects.
It reuses production RecordField/RecordShape data, TypedDict/stub emission, and
Pydantic record-schema emission. New capture and matching behavior is a finite
prototype kernel. Passing its cases demonstrates feasibility, not implemented
production compiler/runtime parity or a complete Python compatibility solver.

The previous 19 POC probes were rerun successfully. All repository `make check`
checks pass: pytest, Ruff lint/format, Flake8 block spacing, mypy and Pyright.
No production source, dependencies, or user-owned union-matrix changes were made.

Installed versions: Python 3.14.3, mypy 2.2.0, Pyright 1.1.411, Pyrefly 1.1.1.
All three checkers accept the positive consumers and directly checked generated
interfaces, and reject every marked negative consumer and derived guard obligation.
There are 18 checker runs across six fixtures. Diagnostics are retained; negative
assertions match authored statement spans because checkers select different
locations within multiline statements. Pyright's stub-only import warnings are
retained separately from the required error checks.

| Area | Validated witness | Practical limit |
| --- | --- | --- |
| Captures | Distinct tokens with equal display names; repeated equality; unbound output failures; nested reuse; failed-branch isolation | Initial prototype scopes; general alias graphs remain unproved |
| Capture unions | Overlapping alternatives produce unions of complete outputs; fixed tuples project element unions | General overlapping generic interfaces remain unproved |
| Matching | Bare unions, whole Is, original-subject branch order, transparent aliases, stable type arguments | Finite compatibility rules, not arbitrary Python typing |
| Special types | Explicit Any union preservation, permissive Any matching, Never/no-match separation, None endpoints, distinct True/1 literals | Production normalization/selection still needs migration |
| Generic compatibility | Invariant lists, covariant Sequence, list/tuple element projection, numeric widening | Custom generic inheritance and protocols need explicit support/diagnostics |
| Fields | Local generic DropCondition; whole-field union Drop; Is distinction; Field defaults; immutable replacement; invalid edits and collisions | No speculative Drop layout or arbitrary field-comprehension support |
| Metadata | Replace discards old type metadata; wrapping retains element constraints; whole-record metadata is omitted | Static interfaces delegate only representable typing facts, not runtime constraints |
| Records | Complete union alternatives; unsupported member fails whole application; generic Box[int] specialization | Cross-module and complete library publication remain integration work |
| Runtime | In-memory definitions without inspect/source files; no body replay; generic model definition, specialization and rebuild; schema-time failure translation | Runtime template validity and compiler source support have distinct boundaries; production integration remains |
| Callables | Restricted int inputs; Any compatibility; safe exact-match output bounds; concrete guard obligations rejected | General flow verification and alias publication were not implemented |
| Future Protocols | Same field data renders required mutable attributes and readonly properties; ordinary objects conform in all three checkers | Future seam witness only; optional attributes, methods and runtime validation are deferred |

## Implementation requirements established by the probes

### Bindings and shared evaluation

Opaque expression templates hide TypeVars from Python substitution. Explicit
identity-based substitution is necessary for local generic aliases and output
types; visible annotation arguments must also carry parameters through Pydantic
specialization. Reuse the existing frontend binding owners rather than adding a
second substitution policy in production.

Extend the shared evaluation context to retain independently named capture
identities and immutable per-attempt environments. Match failure discards tentative
bindings; union alternatives retain separate environments and evaluate complete
outputs separately. Record transforms need a whole-field reference and property
edits rather than rebuilding every passthrough as an old Field marker. Preserve
complete record alternatives until output construction.

### Compatibility cannot reuse current predicates unchanged

Direct probes of current adapters return false for runtime Any-to-int, runtime
Sequence[bool]-to-Sequence[int], runtime int-to-float, and compiler bool-to-int.
All are accepted under the approved checker-compatible direction. Numeric widening
shows why nominal inheritance checks alone are insufficient.

The prototype handles these finite witnesses explicitly. Production needs a
deliberate shared compatibility contract with frontend-owned type facts and an
explicit supported frontier. An unsupported relation must produce a modeled
diagnostic or remain unresolved, rather than masquerading as a proven false match
and silently selecting a default. General protocol/generic compatibility is not
derisked by this finite experiment.

### Checker precision and accepted inputs

A plain `element[T](value: Sequence[T]) -> T` inferred object in mypy for a
tuple[int, str]. Adding a two-element generic tuple overload preserves int-or-str
in all three tools. The initial failed witness is retained. Tuple specialization
must have an explicit frontier; this result does not promise arbitrary-arity
union extraction through ordinary Python typing.

Exact int matching cannot be represented by an int parameter alone, since that
parameter accepts bool and other subclasses. A bool-specific bytes overload,
followed by int/object overloads with str-or-bytes output bounds, is accepted by
all three checkers and is sound for the exercised exact-match cases. Broader
overlap and call inference remain checks for the owning implementation slice.

The approved no-default relationship projects to `convert(value: int) -> str` in
the concrete witness. All three tools reject strings, object-typed values and
unbounded parameters while accepting bool, bounded parameters and Any. The current
overlay instead also emits an unrestricted generic fallback with str-or-Never
output; that fallback must be removed or restricted when it hides unsupported input.

Derived bytes assignments for original bool and int-or-str subjects let all three
checkers reject the str return of the guarded Is example. This is a concrete
obligation witness, not integration of a general control-flow proof engine.

### Failure translation and record-family boundaries

Translate modeled semantic failures at the Pydantic hook boundary. An initial
prototype let frozen domain exceptions escape into Pydantic/contextlib, which
attempted to mutate their traceback and masked the original error. Translating
once to PydanticSchemaGenerationError preserves duplicate-name, no-match and
unsupported-member failures during schema construction. Production's existing
typed-result/issue translation boundary is the appropriate owner.

Keep record transformation separate from family construction. The production
TypedDict emitter already rejects a PROTOCOL-tagged shape, and the same required
field data can form a Protocol interface understood by all three checkers. This
supports the future extension seam without defining optional-attribute semantics
or implementing Protocol reflection/runtime validation now.

## Runtime body finding and resolved policy

The compiler prototype rejects ordinary if/for statements, arbitrary calls,
mutation and filtered comprehensions with authored line/column data. Runtime
symbolic construction accepts literal control flow and a True filter, and executes
a benign side-effecting append before returning a valid template. Symbolic
truthiness rejects only conditions involving symbolic values.

Runtime execution cannot determine all original syntax from the resulting template.
The user resolved this finding on 2026-09-30 by approving the
[runtime construction and compiler support decision](map-selection-decisions.md#runtime-construction-and-compiler-support).
The supported API must agree on type results; compiler and runtime need not reject
every additional Python statement identically. A required compilation step or
source-validation pass is outside the chosen runtime construction model.

The probes above witness the differing source-form acceptance. They do not
implement the production decorator or expand the compiler's supported forms.

## Implementation gates still required

Each union-related slice remains marked for derisking during implementation.
These remaining checks establish production integration, beyond the bounded POC:

- General compatibility frontier, imported classes/protocols, custom generic
  inheritance, literal policy, bounds and constrained parameters.
- Authored origins through compilation plans, overlay checks and proxy mapping;
  complete public interfaces, cross-module aliases and deterministic generated names.
- Unknown/speculative record layouts and Drop outcomes, nested field scopes,
  multiple parameters, unsupported/cyclic type-function composition and metadata.
- Portable generic publication and finite tuple/callable specialization limits;
  truthful fallback and acceptance boundaries for every supported checker.
- Runtime template validity, modeled semantic failures, and shared type-result
  parity; compiler diagnostics for source forms outside its supported subset.

The report supports planning the feature slices. It does not justify shipping a
second evaluator, treating supported witnesses as general inference, or declaring
the complete frontend/proxy feature implemented.

## Reproduction

Retained throwaway repository:
`/Users/neilwadden/.codex/visualizations/2026/09/07/01a07d18-ce62-7e82-bf3c-06a7362ad7d9/typeforge-derisk-poc`.
Branch: `neil/typeforge-derisk-poc`. Commit: `fb784b0`.
The README, executable fixtures, JSON results,
generated interfaces and checker diagnostics are preserved there.

```sh
rtk proxy /Users/neilwadden/Programming/typeforge/.venv/bin/python \
  /Users/neilwadden/.codex/visualizations/2026/09/07/01a07d18-ce62-7e82-bf3c-06a7362ad7d9/typeforge-derisk-poc/verify.py
```
