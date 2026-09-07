# Map slice syntax: authoring and migration contract

Status: Authoring contract settled — slice 01 complete. Slice 02's union
investigation is complete with explicit follow-up gates; production
public runtime construction is complete through slice 03. Remaining integration
and cross-consumer union semantics are not complete.

Task: [Map slice syntax migration, slice 01](map-slice-syntax.md#01--settle-the-authoring-and-migration-contract).
Evidence: [Feasibility POC](../ideas/map-slice-poc.md), `08d940a`.

This document specifies the target public behavior. Slice 03 implements runtime
construction through the public export; remaining source normalization, aliases,
and consumer integration are assigned to slices 04–11. Union decisions remain
subject to slice 02's explicit gates.

## Outcome and success evidence

An author expresses a type relationship once using ordered `selector: output`
branches. Supported uses compile into ordinary checker types or integrate with
Pydantic without requiring a second relationship language.

```python
type Encoded[T] = Map[
    T,
    int: str,
    Assignable[bytes]: str,
    ...: T,
]
```

Success requires equivalent meaning across source and runtime normalization,
portable generated interfaces, working generic substitution, and diagnostics
that name authored expressions. A valid Python parse alone is insufficient.

## Decision ledger

### Accepted direction and inherited rules

- `Map` remains the sole general conditional mapping operator; no `If` is added.
- Branches use slice spelling; plain concrete selectors match exactly.
- Structural patterns retain existing captures. They are not lowered blindly
  into boolean equality comparisons.
- Predicates can explicitly state a comparison or receive the enclosing Map's
  subject when written in unary form.
- Declaration order determines the first matching branch; `...:` is the explicit
  final fallback. Missing fallback and an explicit `Never` output stay distinct.
- Source analysis never imports or executes authored application code.
- Normalize to existing owned representations; preserve the evaluator, consumer
  policies, and finite representability constraints.
- Every union-bearing rule below follows slice 02's evidence and follow-up gates.

### Authoring decisions

| ID | Question | Confirmed contract | Decision owner |
| --- | --- | --- | --- |
| D1 | None versus omitted endpoints | Allow None and empty endpoints as equivalent. An empty endpoint denotes the None type, not Never or a wildcard. | Neil, slice 01 |
| D2 | Old Case/Default authoring | Confirmed: remove it from the public surface at cutover; retain internal representations as needed. | Neil, slice 01 |
| D3 | Bare string selectors and Ruff | Confirmed: require Literal["text"] until tooling supports bare strings. | Neil, slice 01; future tooling work in 10 |

All three preferences were explicitly confirmed by Neil. No-match behavior is
unchanged: omitting a fallback does not mean selecting the None type.

### Implementation decisions within the approved direction

- Retain the existing name `Equal`; this task does not add an `Equals` synonym.
- Separate the public authoring constructor from the canonical marker identity
  recognized by Typeforge frontends. The concrete Python implementation of that
  separation belongs to slice 03.
- Normalize runtime slices before generic parameter discovery/substitution can
  lose their nested parameters. Resolve alias-dependent binding at the existing
  frontend alias seam before final predicate validation.
- Bare literal convenience applies to selector positions. Ordinary output type
  expressions retain their typing meaning.
- A slice step whose value is not None is invalid. An explicit None step is
  equivalent to an omitted step in both frontends; Python erases the distinction.
- This task does not promise raw, unprocessed slice annotations are accepted by
  mypy, Pyright, or Pyrefly. Authored code uses Typeforge's checker integration;
  published consumers receive standard stubs.

## Public forms and roles

`Map[Subject, Selector: Output, ..., ...: Fallback]` requires one subject and at
least one branch. The fallback is optional and counts as a branch. Commas separate
branches; a trailing comma is allowed. The sketch's middle `...` denotes repeated
branches, not an additional valid argument.

The subject is a supported type expression or existing contextual binding such
as Key, Value, or runtime Input. Static literal subjects use `Literal[...]`;
this migration does not add arbitrary value expressions as subject shorthand.

The output is a supported type expression or a field result in an existing
MapFields context. An output of `str` denotes the type str; it does not construct
a string or transform application values by itself. Pydantic separately validates
against the selected output. Literal-valued output types remain `Literal[...]`.

### Selectors and predicates

| Form | Meaning |
| --- | --- |
| `int: str` | Match exactly int, then produce str. bool is not an exact int match. |
| `Equal[int]: str` | Compare the enclosing subject with int using the existing Equal predicate. |
| `Assignable[int]: str` | Test assignability from the enclosing subject to int. |
| `Equal[T, int]: str` | Compare the explicit operands; do not insert another subject. |
| `Assignable[T, int]: str` | Test the explicit source-to-target relationship. |
| `All[Assignable[int], Not[Equal[bool]]]: str` | Bind unary operands to the same enclosing subject, then use existing predicate composition. |
| `Literal[True]: str` | Match the literal True, not arbitrary bool. |
| `True: str`, `1: str`, `b"x": str` | Selector sugar for the corresponding Literal type. Literal equality distinguishes value types; True is not 1. |
| `Literal["text"]: str` | Match the literal string text. Bare `"text": str` is rejected under D3. |
| `list[Value]: tuple[Value, ...]` | Retain existing structural capture and output-template behavior where the consumer supports it. |
| `...: bytes` | Select bytes only if no prior branch matches. |

The existing exact treatment of typing.Any remains distinct from a catch-all.
Use `...:` for a fallback. All/Any/Not retain existing arities and short-circuit
semantics; Typeforge's Any predicate is distinct from typing.Any.

Direct literal sugar covers bytes, bool, and int, including signed integer
literals. Strings require Literal under D3; None follows D1. Arbitrary
expressions, float/complex literals, and enum-value shorthand are not new
selector conveniences in this scope. Supported enum and other literal types
retain explicit `Literal[...]` spelling.

For a unary predicate target, a direct literal uses the same selector rules:
write `Equal[Literal["text"]]`, not `Equal["text"]`. Explicit binary predicates
retain their existing operand roles; write `Equal[T, Literal["text"]]` to make
that value comparison explicit. This migration does not reinterpret strings
throughout arbitrary type expressions or introduce selector forward references.

Structural captures belong to pattern matching. Explicit `Equal[list[Value]]`
does not introduce a capture: Value would need an existing contextual binding.
Parameterized runtime Input patterns retain their current rejection; Input does
not inspect container contents to infer static generic arguments.

### Subject and capture scope

Implicit predicate subjects bind at the consuming Map selector, including when
the predicate is provided by a reusable alias:

```python
type Numeric = Assignable[int]
type Selected[T] = Map[T, Numeric: str, ...: bytes]
```

A reusable unary predicate alias may be declared without a bound subject. When
consumed as a predicate, it must bind through a Map selector or fail explicitly
as unbound. It is not an ordinary output type and must not silently inherit an
implicit subject merely because it appears somewhere in an output expression.

Nested Maps bind their own implicit subjects:

```python
type Nested[T] = Map[
    T,
    int: Map[bytes, Assignable[bytes]: str, ...: float],
    ...: T,
]
```

The inner predicate compares bytes with bytes, not T with bytes. Explicit alias
type parameters retain their own symbol identities. Equal spellings in different
generic scopes do not create shared symbols.

Field Key/Value and structural Value captures retain existing scope rules;
implicit predicate binding must not repurpose either placeholder as a new Map
subject marker. Failed branches must not leak captures into siblings. Recursive
Typeforge aliases and unsupported alias forms retain explicit failures.

### Ordering, defaults, and failures

- Evaluate branches in declaration order; the first definite match wins. Never
  reorder by apparent specificity or deduplicate equal-looking selectors.
- At most one fallback is allowed, and it must be last. A fallback-only Map is
  valid. A later branch is invalid even when it appears unreachable.
- Indeterminate static selection retains the existing reachable alternatives
  and provenance. Slice 02 confirms this distinction through source lowering;
  production consumers must retain it under G7.
- Omission of a fallback preserves a no-match outcome. Compiler policy can
  represent it as Never; runtime integration can reject it. An explicit Never
  branch remains a selected output, not a missing match.
- Semantic predicate failures are not mismatches. Existing short-circuit rules
  determine whether a semantic operand is reached; malformed annotation syntax
  is still invalid.
- Deferred Input chooses a branch before output coercion. Validation failure
  does not retry a subsequent branch or fallback. Serialization retains existing
  behavior; no branch-history wrapper is introduced.

### Endpoint and step rules

An omitted branch/fallback is different from an omitted slice endpoint.
`Map[T, int:str]` has no fallback: an unmatched subject produces a no-match
outcome. In contrast, `Map[T, :str]` contains a branch with a missing selector.
Python represents that selector exactly as if it had been spelled None.

Under confirmed D1, the following pairs are accepted with the same semantics.
Prefer explicit None in examples for readability; empty endpoints are valid.

| Authored forms | Meaning |
| --- | --- |
| `None: str` and `:str` | Match the None type, produce str. |
| `int: None` and `int:` | Match int, produce the None type. |
| `...: None` and `...:` | Fallback to the None type. |
| `None: None` and `:` | Match the None type, produce the None type; this is not a fallback. |
| `int: str` and `int: str:None` | Same branch; the step carries no operation. |
| `int: str:bytes` | Invalid non-None step. |

Normalize the None endpoint to the existing None-type representation. NoneType
remains an explicit alternative. There is no missing-endpoint error under this
contract: Python's inability to distinguish an omitted endpoint from None is
reflected deliberately in the language. The POC's endpoint rejection is
superseded by this decision and must not be promoted as a production contract.

The AST preserves spelling distinctions that runtime slices erase. Diagnostic
messages may describe the available representation; neither frontend may claim
it can reconstruct missing source spelling from a runtime slice. This is separate
from requiring consistent semantics for indistinguishable values.

## Supported, rejected, and deferred behavior matrix

"Supported" here means required at migration completion, not already implemented.
Rows do not widen existing consumer representability or record-family support.

| ID | Example or condition | Target status | Expected observation | Delivery owner |
| --- | --- | --- | --- | --- |
| M01 | `Map[int, int:str, ...:bytes]` | Supported | Select str in static and runtime semantics. | 03, 04, 07, 08 |
| M02 | `Map[bool, int:str, ...:bytes]` | Supported | Exact int selector does not match bool. | 07, 08 |
| M03 | `Map[bool, Assignable[int]:str, ...:bytes]` | Supported subject to existing consumer capabilities | Unary binding agrees with the existing explicit binary predicate. | 03–05, 07, 08 |
| M04 | `Map[Literal[True], True:str, ...:bytes]` | Supported | Literal matching preserves type/value distinctions. | 03, 04, 07, 08 |
| M05 | `Map[Literal["text"], Literal["text"]:str]` | Supported | Match the literal; reject bare string selectors until tooling support is established. | 03, 04, 10 |
| M06 | `Map[T, Numeric:str, ...:bytes]` | Supported | Alias expansion precedes final unary-predicate validation. | 05 |
| M07 | Nested Maps and explicit binary predicates | Supported | Each unary predicate binds locally; explicit operands remain explicit. | 05, 07, 08 |
| M08 | `Map[list[int], list[Value]:tuple[Value, ...]]` in Schema | Supported | Capture int and construct the selected tuple type. | 07, 08 |
| M09 | Unbounded callable structural form from the POC | Deferred existing limitation | Do not claim the syntax migration fixes its existing emission failure. | Callable-lowering follow-up, tracked by 07 |
| M10 | `Map[int, int:list[T], ...:T]` specialized with T=str | Supported | Parameters that occur only in outputs remain discoverable and substitute. | 03, 08 |
| M11 | `Map[T, ...:bytes]` | Supported | Fallback-only mapping. | 03, 04 |
| M12 | `Map[T]`, non-branch entries, duplicate/default-following entries | Rejected | Modeled invalid-annotation failure at the consuming interface. | 03, 04, 10 |
| M13 | Equal selectors in two branches | Supported | Preserve both branches and declaration order; the first matching one wins. | 03, 04, 07, 08 |
| M14 | None or omitted endpoint | Supported | Both denote the None type; no-match remains a separate outcome. | 03, 04 |
| M15 | Non-None slice step | Rejected | No third-operand operation is invented. | 03, 04, 10 |
| M16 | Reached no-match versus explicit Never | Supported policy distinction | Preserve the original outcome and each consumer's translation. | 07, 08, 10 |
| M17 | Invalid selected Input output | Rejected validation | No attempt to select another branch. | 08 |
| M18 | Parameterized/capturing Input selector | Rejected existing limitation | No inference of static container argument types from raw values. | 08 |
| M19 | Inline return annotations and named aliases | Supported through Typeforge | All supported checker-visible annotations are projected to ordinary types. | 06 |
| M20 | Raw slice annotations checked without Typeforge | Not promised | No claim that object fallback makes slices valid checker type arguments. | 03, 06, 10 |
| M21 | Slice Map inside existing MapFields | Supported | Preserve existing field modifier, name/type-role, and duplicate-name semantics. | 09 |
| M22 | Legacy Case/Default public authoring | Rejected after cutover | Remove old public authoring; internal canonical data may remain. | 03, 04, 11 |
| M23 | Unary predicate consumed outside a binding selector | Rejected as unbound | Declaring the alias is valid; using it without its required subject is not. | 05, 10 |
| M24 | Union subjects, selectors, outputs, aliases, or speculative alternatives | Investigated; follow-up gates open | Follow the slice 02 evidence and G1–G7; no blanket support promise. | 03–10 as assigned in the findings |

## Constructor identity, interfaces, and ownership

The authoring constructor is the public `from typeforge import Map` subscription
interface. Its responsibility is to preserve and normalize declarative annotation
data early enough that generic substitution remains correct. It does not select
branches or validate application values.

Canonical marker identity is owned by Typeforge's base marker module. Frontends
recognize canonical objects directly rather than assuming every canonical origin
must equal the public authoring constructor. The POC's separately imported facade
demonstrates this distinction; production should not require that extra import.
This contract does not promise a particular class/metaclass implementation or
that `get_origin(expression) is Map` remains the recognition rule.

Equivalent normalized expressions preserve ordinary parameter discovery,
specialization, equality, and hashing where their constituent typing objects
support those operations. Do not store raw slices in a representation where
Python will overlook their type parameters.

| Owning module | Responsibility and observable seam |
| --- | --- |
| `typeforge._markers` and public exports | Public annotation construction, canonical marker identity, base fallback behavior, optional-dependency isolation. Observe via public subscriptions and standard typing introspection. |
| `compiler.source` | Recognize imported syntax; preserve source locations; normalize syntax into existing source data. Observe via parse_source and the compiler consumers. |
| Compiler adaptation / existing source alias expansion | Resolve aliases and predicate operands before final semantic validation, retaining authored type identity and origin. |
| `typeforge.pydantic._frontend` | Adapt runtime annotations and expand aliases into existing semantic data; cooperate with early construction normalization. |
| `semantics` | Existing matching, predicate composition, captures, reachability, and no-match facts. No second evaluator. |
| Compiler specialization / emission | Represent supported callable relationships and publish deterministic complete interfaces. Observe via generate_module and checker consumers. |
| `overlay` | Project retained contracts into ordinary checker annotations and preserve authored mappings. Observe via transform_source and real checkers. |
| `typeforge.pydantic.Schema` | Public runtime integration seam; Pydantic owns model lifecycle, validation, metadata, and serialization. Observe via TypeAdapter and BaseModel. |

Runtime construction and source parsing are distinct normalization points because
they receive different representations. Their behavior contract is shared; a
generic AST/runtime adapter framework is not required by this specification.
Alias expansion stays with its existing owner instead of being duplicated inside
the public constructor.

Slice 03 implements runtime construction in `typeforge._map`, exported publicly
as Map at runtime. The canonical alias remains `typeforge._markers.Map`; the
typing-only public import retains that object fallback. Constructed GenericAlias
arguments contain existing Case/Default data, so Pydantic only changes its marker
identity import. Runtime Doc metadata remains available on the constructor.
Legacy branch aliases remain opaque until frontend validation during migration.

Malformed construction must fail through an appropriate annotation-construction
exception; compiler entry points retain their typed failure results. Pydantic
adaptation/planning retains modeled issues and translates them at its public
exception seam. Unexpected exceptions must not be turned into no-match outcomes.
Private canonical names must not replace authored spelling in diagnostic text.

### Fallback typing

Base Map remains inert and conservatively object-like when its typing fallback
is consumed without relationship evaluation. That fallback is independent of
whether a raw authored expression is legal to a checker.

Published relationship aliases retain the existing conservative object fallback;
specialized callable interfaces retain their existing portable output contract.
Overlays retain the existing possible-output fallback policy. Slice 02 exercises
union bounds in named-alias overlays; inline projection remains gated by G7.
Do not replace the bound with Any or silently narrow it to one branch.

## Union investigation and implementation handoff

Slice 02's [findings and executable matrix](map-slice-union-findings.md) now
record observed outcomes and assign G1–G7 to implementation owners. Old and slice
spellings agree in the tested matrix, but existing consumer differences prevent
a blanket portable-union contract. In particular, bare exact selectors and
explicit Equal predicates differ on union subjects; unary binding still uses the
whole enclosing subject. The migration must not silently reinterpret that scope.

The table below preserves slice 01's investigation questions. Read it alongside
the findings; it does not supersede the observed limits or approve semantic fixes.

The following are investigation hypotheses, not newly approved semantics:

| Position | Provisional direction | Required evidence |
| --- | --- | --- |
| Subject union | Preserve existing distribution where defined. | Per-member first-match ordering, defaults, and unmatched-member behavior across consumers. |
| Bare selector union | Do not assume `int | str` means either-member matching under an exact-match default. | Decide identity versus member matching from existing semantics and the intended surface; return any semantic change for agreement. |
| Union predicate target | Preserve Equal versus Assignable distinctions. | Whole-type comparisons, distribution interactions, and runtime Input observations. |
| Output union | Preserve the authored union type. | Construction/substitution, schema output, checker emission, and validation/serialization behavior. |
| Outer union such as `Map[...] | None` | Keep supported composition if it can be represented faithfully. | Canonical marker construction and all frontend traversals. |
| Aliases/captures containing unions | Preserve bindings and groupings. | Alias expansion, symbol identity, nested subject binding, and capture behavior. |
| Indeterminate selection | Preserve possible-output provenance and reachability. | Do not confuse speculative alternatives with a definitely selected union. |

**Every row has slice 02 evidence; its follow-up gates still apply.** Any uncovered
union position introduced later must receive its own matrix entry and slice note.
Existing union behavior remains
a constraint; this contract does not authorize changing it as a side effect of
syntax normalization.

## Migration and acceptance

Confirmed D2 is a coordinated breaking authoring cutover: public documentation,
exports, fixtures, and repository callers move to slice syntax together. Existing
Case/Default data can stay private to normalization and evaluation. Implementation
may retain the old public form while migrating identified repository consumers,
with removal required before slice 11 completes. There is no indefinite public
compatibility promise after cutover.

There is no transitional public release of old authoring in this plan.
Historical POC evidence remains historical even after its executable facade
and tests are migrated. D3 requires migrating the POC's bare string examples to
Literal spelling; no user lint suppressions are part of the supported initial
authoring contract. Revisit bare strings only after tooling support is established.

The smallest delivery tracer after contract approval is public construction and
generic specialization:

```python
T = TypeVar("T")
expression = Map[int, int: list[T], ...: bytes]
specialized = expression[str]
```

Observe through the public subscription interface and standard typing
introspection that T is discoverable before specialization and is replaced in
the output afterwards. A known runtime consumer of the specialized annotation
must select list[str]. The POC established that the current public marker loses
this output-only parameter inside a raw slice.

This tracer was implemented in slice 03 as
`test_output_only_parameter_is_discovered_and_specialized`, with an observed
failure before implementation and a normal passing regression afterwards.
Additional matrix rows supply candidates for later vertical contracts; do not
add a batch of pending production tests while union scope remains open.

Slice 01 records the confirmed D1–D3, the non-union behavior matrix and ownership
contract, and the union hypotheses handed off to 02 with their risks intact.
There are no remaining slice-01 preference questions. Validation for this slice
checks links, examples, decision consistency, and scope; production capability
checks belong to their implementation slices.
