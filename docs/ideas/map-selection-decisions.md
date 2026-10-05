# Map selection decisions

Latest direction: type-function scope and Record/Fields comprehensions are the
goal API. Concrete bare union matching is memberwise; Is compares the whole type
in the agreed examples. Generic arguments remain stable and named captures bind
matched types. Unresolved relationships remain internal with useful standard
output projections. Mixed bare/Is branch ordering is agreed. The second decision
batch removes public Assignable and defers compound predicates and binary
comparisons from the initial API. The language comparisons below are exploratory history.
Latest correction: a bare Animal selector must match Dog when Dog subclasses
Animal. After requesting checker verification, the user chose to follow their
lead on bool/int compatibility: bool matches bare int. The proposed primitive
exception is withdrawn. Any and generic compatibility decisions are also agreed;
their implementation and the revised default lowering still need derisking.

Design constraint: minimize Typeforge-specific checking and continue delegating
ordinary Python type inference and expression compatibility to existing checkers.
Evaluate unresolved-match proposals against this constraint, not only IDE display.
Agreed checking scope: retain unresolved relationships internally, project useful
standard types, and generate supported obligations for existing checkers. Make
bound-only coverage explicit; full Scala-style dependent checking is not promised.

Public-surface decision: remove Assignable. Earlier Assignable examples document
the explored operation; they are not initial public API contracts. Bare matching
provides memberwise compatibility and Is provides exact whole-type matching.
Whole-union assignability selection is outside the initial public surface.

Status: Initial-scope workshop decisions complete as of 2026-09-30. All discussion
checklist groups below are agreed. Derisking and production implementation remain
pending. The latest agreed batches govern; older exploratory proposals and current
implementation evidence do not override them. Future Protocol support and NewType
semantics remain outside this initial scope.

The [2026-09-30 derisking report](type-function-derisking.md) validates the bounded
witnesses. The resulting [runtime construction decision](#runtime-construction-and-compiler-support)
keeps compilation optional; supported type results must agree, while source-form
rejection may differ between the compiler and runtime.

Binding syntax review led to explicit reusable names. After revisiting D7 with
named captures, the user approved separate output evaluation for each successful
alternative and a union of complete results. See [binding syntax](#reopened--binding-syntax).
The user has selected type-function scope with Record/Fields comprehensions as
the preferred field-authoring direction, subject to feasibility work below.
The [record-comprehension POC](record-comprehension-poc.md) now demonstrates the
core syntax through compiler adapters and runtime Schema construction. It identifies
required template bindings, a field-reference operation, and record alternatives;
production integration and broader contract validation remain pending.
After reviewing the POC, the user confirmed this form as the goal API. The workshop
has now settled its initial syntax and semantics; production work awaits derisking
and implementation planning.

Capture the expected outputs before implementing changes to union selection,
callable precision, or field transforms. Current behavior below is evidence,
not a desired contract. Proposed alternatives are not implementation approval.

Related references: [current support](../../CONTEXT.md),
[union matrix](../../tests/unit/test_slice_union_matrix.py), and
[callable cutover](callable-map-semantics-cutover.md).

## Discussion checklist

- [x] Remove public Assignable; defer compound predicates and binary comparisons (decision only).
- [x] D1: Union selectors, subject distribution, and initial selector surface (decision only).
- [x] D2: Union equality independent of member order (decision only).
- [x] D3: Ordinary union aliases in subjects, selectors, and predicate operands (decision only).
- [x] D4: Any-containing union subjects and outputs (decision only).
- [x] D5: Union-valued field transforms (decision only).
- [x] D6: Callable selection, guard verification, and input-contract projection (decision only).
- [x] D7: Unsupported record unions and unions of capture patterns (decision only).
- [x] F1: Initial field construction, edits, metadata, and record output (decision only).
- [x] D8: Concrete no-match, Never, and runtime failure-phase rules (decision only).
- [x] Separate runtime template construction from compiler source support; keep compilation optional (decision only).

Every union-related group needs derisking before implementation. Record semantic
output separately from emitted checker types and runtime acceptance: an output
type does not by itself specify which raw values validate.

### Workshop agenda — audited 2026-09-11, settled 2026-09-30

The six groups identified in the audit are now settled for the initial scope.
Implementation edge cases still need probes. Older exploratory sections contain
superseded open questions; the latest agreed examples take precedence.

1. Selector surface: settled in the second batch below.
2. Unresolved callable contracts: settled in the final callable batch below.
3. Field construction: settled in the second batch below; edits and collisions
   were settled in the first batch.
4. Record preservation: initial TypedDict output and metadata policy settled in
   the second batch, with future generated Protocol support an explicit design
   constraint rather than initial implementation scope.
5. Type-function language boundary: the first batch defines compiler-supported
   forms; the runtime construction decision below settles the enforcement boundary.
6. Public cutover: agreed in the first batch below. Breaking changes are acceptable
   before release; migration guides and a compatibility period are unnecessary.

Do not reopen agreed distribution, Is equality, alias transparency, Any matching,
variance, capture consistency/isolation, union capture outputs, or concrete failure
rules merely to confirm their consequences. Additional compatibility forms such as
literals and protocols need conformance probes and explicit support boundaries;
bring a case back only if checker disagreement or a material scope tradeoff needs
a decision. NewType remains explicitly deferred.

Keep implementation derisking separate: generic interface projection, record and
capture unions, runtime templates, overload precision/order, and diagnostic mapping
still need validation. Failed probes may reveal new decisions, but those checks
are not additional unsettled examples today.

### Runtime construction and compiler support

Agreed 2026-09-30 after reviewing the derisking findings. This decision supersedes
earlier requirements for identical compiler/runtime rejection of body syntax.

Runtime use works through normal Python imports. Compilation, source-file access,
and a saved compiler artifact are optional. The decorator executes the body once
with unresolved type parameters to construct an immutable symbolic template.
Specialization and ordinary value validation use that template without rerunning
the body.

Runtime accepts Python code that produces a valid Typeforge template. Ordinary
control flow, loops, and calls may therefore work during construction even when
the compiler cannot support their source forms. Use Map for type-dependent
selection involving unresolved type symbols; symbolic truthiness remains invalid.
Runtime template construction and type evaluation still enforce their semantic
rules and report modeled failures.

The compiler reads authored source without importing or executing it. Initially,
it supports the body forms listed in the first decision batch. Other forms receive
an authored-source diagnostic rather than an execution fallback. Compiler support
may expand independently of runtime construction.

The supported API must produce the same type results in both paths. Identical
rejection of every additional Python statement is not required. Runtime acceptance
alone does not establish compiler support. This is an agreed design boundary;
production implementation remains pending.

### First decision batch — agreed

Field edits and collisions:

- Duplicate output names fail, even when the colliding fields have equal types.
- Invalid field names and modifier values fail.
- Drop removes a field when returned directly or produced by field.replace(type=...).
  Drop in name, required, or readonly fails.

Initial compiler-supported type-function language:

- Support capture declarations using the discussed Capture("Item") spelling,
  local aliases including generic aliases, and applications of other type functions
  through subscription.
- Support field edits and Record(... for field in Fields[T]) comprehensions.
- Require one final return. Ordinary if/for statements, mutation, recursion, and
  arbitrary function calls are unsupported by the initial compiler. Map supplies
  type-dependent conditional selection. Approved symbolic operations are explicit
  exceptions to the arbitrary-call restriction.
- Composition such as a local alias Visible = Public[T], followed by a field
  comprehension over Fields[Visible], is intended to work.
- Runtime construction follows the [separate boundary above](#runtime-construction-and-compiler-support);
  these compiler source restrictions are not runtime rejection rules.

Public cutover:

- Replace MapFields authoring with Record/Fields and ambient Key/Value authoring
  with field references and named captures.
- Replace superseded field constructors once the new-field authoring surface is
  settled. Internal representations may remain where they have actual consumers.
- The library is unreleased. Breaking changes are acceptable; migration guides,
  compatibility shims, a deprecation period, and special migration diagnostics
  are not requirements. Update repository consumers, examples, and public docs
  to the resulting API as part of implementation.

These are design approvals, not authorization to begin production implementation.

### Second decision batch — agreed

Initial selector surface:

- Bare selectors provide memberwise compatibility matching; Is provides exact
  whole-type matching.
- Remove public Assignable. Compound predicate helpers and explicit binary
  comparisons are outside the initial API. Whole-union assignability tests are
  consequently unavailable initially; Is does not replace that operation.

New-field construction:

```python
Field(name="display_name", type=str, required=False, readonly=True)
```

Name and type are required keyword arguments. Required defaults to True; readonly
defaults to False. Use Field to create a field and field.replace to preserve an
existing field while changing selected properties. This replaces the separate
OptionalField and ReadonlyField constructors at cutover.

Initial records and future object support:

- Fields accepts supported TypedDict inputs and their agreed unions; Record
  produces new TypedDict shapes in the initial pass.
- Preserve field types, modifiers, and type-attached metadata under the agreed
  rules. Do not automatically copy whole-record metadata; authors apply it
  explicitly to the resulting record.
- The user explicitly requires leaving room for object support through generated
  Protocol definitions. TypedDict is the initial output family, not a permanent
  restriction of the shared field-transform model.
- Keep field transformation separate from family-specific reflection and output
  construction. Preserve record-family identity; do not route every future object
  shape through TypedDict conversion or dictionary access assumptions.
- Reuse the existing RecordShape/RecordFamily distinction. RecordFamily already
  includes PROTOCOL, but this is not evidence of implemented Protocol support.
  DESIGN.md already requires explicit adapters for distinct record families.
- A future Protocol adapter must model attribute access, mutability, properties,
  and any supported methods deliberately. TypedDict requiredness must not be
  assumed equivalent to an optional object attribute. These future semantics and
  public output-family selection syntax are deferred, not decided by this batch.
- Static Protocol output must be expressed as standard checker-visible
  declarations without executing authored code. Runtime Protocol generation and
  validation require their own adapter/derisking; they are not implied by the
  TypedDict POC. Do not add a speculative framework or implement Protocols now.

The final callable batch below settles the remaining workshop group. Implementation
probes may expose additional choices; all initial-scope groups are now agreed,
including this explicit future-object-support constraint.

## Assignable public surface — historical discussion, resolved by second batch

The discussion below predates approval to remove public Assignable. Read it as
design history; the second decision batch defines the initial public surface.

The guard example prompted the user to reconsider whether Assignable provides
enough value to justify its complexity. This is a design discussion, not an
instruction to remove the implementation yet.

The distinctive capability is selecting by assignment compatibility rather than
exact member matching: one branch can cover a base class and subclasses that
were not enumerated when the Map was authored. Existing runtime Input tests
exercise subclass acceptance. General protocol and generic compatibility should
not be presented as complete merely because the helper is named Assignable;
the current source and runtime adapters implement limited relations.

Bare selectors, Is, structural captures, field transforms, and Each/Collect do
not conceptually require a public Assignable helper. Removing it would reduce
public concepts but lose open-ended compatibility selection. It should not be
silently replaced with subtype matching in bare selectors, which would change
the agreed exact-member rule.

The guard problem also arises with whole-subject Is: a subject int-or-str is
not exactly int even when the current value is an int. Removing Assignable
therefore does not eliminate the need to distinguish static type parameters
from narrowed values in implementation verification.

Earlier recommendation under discussion: defer/remove public Assignable unless
an identified near-term feature requires compatibility selection. A subsequent
[comparison with other languages](type-selector-precedents.md) suggests first
separating three design questions: the comparison relation, union distribution,
and static versus runtime selection. Removal is still undecided.

The user initially preferred TypeScript-inspired distribution for its informative
IDE outputs, then reconsidered Scala-style matching after clarifying that an
unresolved match can also expose a possible-output bound. They now lean toward
the latter, pending representation details. Comparison relation, distribution,
and presentation remain separate questions; helper retention and scope syntax
are not settled.

If removal is chosen, explicitly migrate public exports, normalization,
diagnostics, examples, and tests, reconcile the earlier Assignable-dependent
decisions, and retain internal operations only where they have consumers.

### Revisited Assignable example — bare subclass matching requested

Now that memberwise matching, whole-type Is, and stable generic/capture bindings
are agreed, the discussion revisited retaining Assignable as an advanced selector.
The user rejected the proposed distinction in this example: both should yield str.

```python
class Animal: ...
class Dog(Animal): ...

Map[Dog, Animal: str, ...: bytes]              # str (user expectation)
Map[Dog, Assignable[Animal]: str, ...: bytes]  # str
```

Bare class matching must therefore accept subclasses. Is remains the exact-type
selector under its existing contract. Assignable's separate public value needs
reassessment; removal has not been authorized. This class example does not by
itself select all Python assignment-compatibility behavior, especially Any,
parameterized types, or whole-subject union compatibility.

## Exploratory TypeScript-style and Scala-style alternatives

These sketches translate the [language precedents](type-selector-precedents.md)
into hypothetical Typeforge authoring. The user is comparing the models again;
neither implementation nor exact new syntax is approved.
Whole below is a placeholder scope wrapper, not an existing helper. The sketches
focus on concrete int/str subjects, not a complete policy for Any, Never,
unresolved generics, or every structural pattern.

### TypeScript-style distribution with explicit whole-subject scope

Rationale: produce an informative combined output type for IDE users rather
than retaining overlap as an unresolved type match. An unresolved model could
also expose a bound; IDE information is not unique to distribution. This model
produces that union directly from memberwise selection.

```python
type Encode[T] = Map[T, Assignable[int]: str, ...: bytes]
type EncodeWhole[T] = Map[Whole[T], Assignable[int]: str, ...: bytes]
```

Under this model, Encode applies the same Map to each top-level union
member. Unary predicates bind to that current member. Encode[int | str] is
therefore str-or-bytes; EncodeWhole[int | str] is bytes because the complete
union is not assignable to int. Both aliases select str for int and bytes for
str. Whole disables distribution; it does not change compatibility to equality.

This is inspired by TypeScript's naked-parameter conditional distribution and
tuple-wrapped non-distribution. It is not a literal import of all TypeScript
rules. In particular, making distribution uniform across selectors would change
our earlier rule that Assignable always compares the whole Map subject.

For Is, the same separation would let Map[T, Is[int]: str, ...: bytes] map each
member, while Map[Whole[T], Is[int]: str, ...: bytes] compares the complete type.
That revises the earlier implicit whole-subject meaning of Is. Reconcile those
example spellings when confirming the opt-out syntax. Structural capture
semantics need separate derisking.

For a function returning Encode[T], an isinstance(value, int) branch returning
str and a non-integer branch returning bytes fit the concrete int/str and
int-or-str examples. This is not a claim that all generic bodies become
automatically verifiable or that Any semantics are resolved by distribution.

### Scala-style whole-subject matching with overlap preservation

```python
type Encode[T] = Map[T, Assignable[int]: str, ...: bytes]
```

In this alternative, the compatibility case is treated as a type pattern:
select it if the whole subject fits, skip it if the subject cannot overlap it,
and otherwise retain the unresolved match. For int, select str. For str, select
bytes once disjointness is established. For int-or-str, neither branch can be
selected conclusively: some values fit the integer case and others do not.

Encode[int | str] therefore remains unresolved under these rules. Typeforge
could expose a str-or-bytes possible-output bound to a checker, but that is a
proposed projection policy, not a concrete selected union or a claim that Scala
automatically substitutes that union. Matching runtime branches would still
need explicit verification rules.

Using Assignable in this sketch names the relationship being explored. Scala's
actual match reduction uses subtyping and disjointness, not Python's gradual
Any assignability. A true Scala-inspired pattern protocol could not simply
interpret a false Assignable Boolean as permission to use the default.

### Distinguishing example

| Model applied to an int-or-str subject | Result |
| --- | --- |
| Memberwise compatibility Map | Selected output union str-or-bytes |
| Whole-subject Boolean compatibility Map | Selected fallback bytes |
| Whole-subject overlap-aware type match | Unresolved match; str-or-bytes is a proposed bound |

The design choice is not only naming. It determines which subject predicates
observe, whether overlap blocks fallback, and what evidence implementation
verification requires.

### Proposed presentation of an unresolved match — not yet agreed

The user asks whether the displayed type would be Unresolved[str | bytes].
Propose keeping the public value type a normal union and presenting uncertainty
as additional information, not as an invented runtime wrapper:

- Authored relationship: Encode[int | str], retaining the original Map.
- Internal state: an unresolved selection with a str-or-bytes possible-output
  bound and the information needed for later evaluation or verification.
- Portable projection: `result: str | bytes`, or an equivalent standard alias.
- Optional Typeforge-aware hover: show that ordinary type plus a note that
  selection is unresolved and this is its possible-output bound.

The exact hover spelling is a UI proposal. An ordinary checker consuming only
the generated union cannot retain or enforce the original dependent relationship.
Typeforge must keep that relationship internally; displaying a bound is not a
substitute for verifying that the implementation satisfies it. Additional type
information can resolve a later specialization, but a value guard does not
automatically refine the original whole subject.

Do not introduce an opaque Unresolved generic as the actual value annotation:
the result is an ordinary str or bytes value, not an instance of that wrapper.
Erasing a hypothetical wrapper to its union would likewise erase its relationship
for ordinary checkers; an annotation name alone cannot provide Scala semantics.

Existing IndeterminateType data retains a possible output and alternatives;
existing proxy hover handling can append documentation. These are relevant
building blocks, not proof that Scala-style reduction or unresolved-selection
hover is already implemented. Sources:
[semantic data](../../src/typeforge/semantics/domain/models.py),
[hover presentation](../../src/typeforge/proxy/hover.py), and
[hover integration](../../src/typeforge/proxy/server.py).

### Proxy delegation and verification boundary

The user wants to minimize Typeforge-owned checking. Current responsibilities
already separate contract construction from ordinary expression checking:

- Typeforge's verification planner recognizes authored control flow and creates
  expected-type obligations from callable relationships.
- The overlay emits ordinary Python annotated assignments and signatures.
- The backend checker validates those expressions; the proxy maps diagnostics
  to authored source and can append hover documentation.

A local probe of the current implementation generated
`__typeforge_return_1: str = b"wrong branch"` for an integer branch returning
bytes. Mypy rejected that assignment. Thus branch-specific Typeforge checks can
be delegated without implementing Python expression inference. Sources:
[verification planner](../../src/typeforge/compiler/verification/planner.py),
[contract construction](../../src/typeforge/compiler/verification/contracts.py),
[overlay emission](../../src/typeforge/overlay/transform.py), and
[proxy routing](../../src/typeforge/proxy/server.py).

Emitting only str-or-bytes checks membership in the bound, not the dependency
between inputs and outputs. Keeping an unresolved expression internally or
showing it in hover does not automatically enforce that dependency. Typeforge
still has to derive sound obligations or represent the relationship using
standard generics and overloads. Existing unknown-flow fallbacks do not provide
full dependent verification.

Agreed checking scope: allow unresolved internal data and
use ordinary output bounds, generics, overloads, and supported verification
obligations at checker boundaries. Document where only a bound is checked.
Do not promise arbitrary Scala-style match-type checking or introduce general
Python type inference to support it. Richer overlap proofs and dependent checks
need separate derisking and an explicit cost/coverage decision; the proxy itself
does not supply those proofs.

This agreement establishes the checking boundary. It does not by itself settle
the remaining distribution, overlap, helper-retention, or public-syntax decisions.

## D1 — Union selectors and distribution

Earlier baseline: the examples, public selector roles, and subtype distinction
below were agreed before the preference for uniform memberwise distribution.
Later examples reaffirm whole-subject Is and mixed branch ordering. The newest
Dog/Animal decision revises scalar exactness for bare class selectors. Other
compatibility cases and compound selectors remain open.

### Agreed direction

Bare union selectors represent alternatives. Known union subjects can produce
the union of their members' mapped outputs. Assignable requires the whole
subject to be assignable to its target; `Is[...]` tests for exactly the same type.
Equal is not public authoring syntax. Its earlier role as the default lowering
operation must be revised for the newly requested bare subclass matching.

| Case | Expression | Agreed output |
| --- | --- | --- |
| U01 | `Map[int \| str, int: bytes, str: float]` | `bytes \| float` |
| U05 | `Map[int, int \| str: bytes, ...: float]` | `bytes` |
| U05-Is | `Map[int, Is[int \| str]: bytes, ...: float]` | `float` |
| U06 | `Map[int \| str, int \| str: bytes, ...: float]` | `bytes` |
| U07-bare | `Map[int \| str, int: bytes, ...: float]` | `bytes \| float` |
| U07-Is | `Map[int \| str, Is[int]: bytes, ...: float]` | `float` |
| U09 | `Map[int, Assignable[int \| str]: bytes, ...: float]` | `bytes` |
| U10 | `Map[int \| str, Assignable[int]: bytes, ...: float]` | `float` |

The discussion calls the Assignable union-target example U08; it corresponds
to U09 in the existing regression matrix. Keep U08 for reversed union equality.

### Public syntax and internal representation

Authors write bare selectors for default matching and Is for exact whole-subject
comparison. They do not write Equal. The earlier plan to lower default matching
to Equal does not implement the subsequently requested Dog/Animal subclass case;
use an appropriate matching operation without changing exact Is or capture
consistency. An explicit Equal spelling was explanatory notation, not another API.

Keep that authoring decision separate from implementation feasibility. Current
Equal evaluation is a whole-subject predicate, so reusing its representation
does not by itself implement memberwise selection. The implementation must
preserve which operation distributes over subject members and which compares
the complete subject.

Existing public Equal examples and consumers will need migration at cutover.
Public compound conditions, explicit binary comparisons, and structural capture
selectors need their own contracts; do not expose internal Equal merely to
preserve their current spelling.

### Current implementation evidence

| Case | Expression | Current compiler / runtime Schema output |
| --- | --- | --- |
| U01 | `Map[int \| str, int: bytes, str: float]` | `bytes \| float` / `bytes \| float` |
| U05 | `Map[int, int \| str: bytes, ...: float]` | `float` / `float` |
| U06 | `Map[int \| str, int \| str: bytes, ...: float]` | `float` / `float` |
| U07 | `Map[int \| str, Equal[int]: bytes, ...: float]` | `float` / `float` |
| U09 | `Map[int, Assignable[int \| str]: bytes, ...: float]` | `bytes` / `bytes` |
| U10 | `Map[int \| str, Assignable[int]: bytes, ...: float]` | `float` / `float` |

Bare selectors currently distribute over subject members, while unary predicates
compare the whole subject. A bare union selector is currently an exact union
type for static selection, alternatives for raw Input, and a subtype-matched
parameter in callable overloads.

### Remaining decisions and derisking

- Specify public All/Any/Not composition and explicit binary comparisons using
  the agreed authoring vocabulary; preserve memberwise versus whole-subject roles.
- Reconcile newly requested bare subclass matching with earlier exact-only cases,
  Assignable retention, and callable interface projection.
- Apply the agreed set equivalence for unions (D2) and alias transparency (D3).
  Do not infer Python object identity from the helper's name.
- Confirm branch order on mixed whole-subject predicates and bare selectors,
  partially matched subjects, and preservation of structural Value captures.
- Check runtime Input and callable projection against these contracts; passing
  the static examples does not establish their behavior automatically.

### Class matching — follow checker compatibility for bool/int

The user expects Dog to match Animal. They initially proposed a primitive
inheritance exception, then asked how mypy, Pyrefly, and other checkers handle
bool/int and instructed us to follow their lead. All three tested checkers accept
bool where int is expected. The resulting goal examples are:

- `Map[bool, int: str, ...: bytes]` produces str.
- `Map[bool, Is[int]: str, ...: bytes]` produces bytes.
- `Map[Dog, Animal: str, ...: bytes]` produces str when Dog subclasses Animal.

The earlier Assignable[bool, int] relationship remains str if that helper is
retained with Python assignment compatibility. A separate primitive category is
not needed for this rule.

Bare int and Is[int] now differ even for the scalar bool subject: compatibility
versus exact type comparison. They also retain their distinct memberwise and
whole-subject scopes. Any, literal matching, and general generic compatibility
still need review; the bool/int investigation does not silently override all
earlier Any decisions.

### Custom subclass of int — checker evidence

```python
class UserId(int): ...

Map[UserId, int: str, ...: bytes]
```

All three tested checkers accept UserId where int is expected. Following the
requested checker-aligned approach gives str here. This is an actual subclass,
not NewType, whose treatment remains deferred.

### Checker probes for bool/int compatibility

After reviewing these results, the user explicitly confirmed following the
checkers' compatibility behavior. The primitive exception is withdrawn.

Tested installed versions: mypy 2.2.0, Pyright 1.1.411, Pyrefly 1.1.1, using the
checkout's Python 3.14 environment. Separate positive and negative files avoid
mistaking absence of an unrelated diagnostic for acceptance.

| Probe | mypy | Pyright | Pyrefly |
| --- | --- | --- | --- |
| bool assigned to int / passed to int parameter | accepted | accepted | accepted |
| int assigned to bool / passed to bool parameter | rejected | rejected | rejected |
| UserId(int) passed to int parameter | accepted | accepted | accepted |
| Sequence[bool] returned as Sequence[int] | accepted | accepted | accepted |
| list[bool] returned as list[int] | rejected | rejected | rejected |

Every positive file passed; each negative file reported exactly three expected
errors (reverse assignment, reverse argument, invariant list return). Sources:
[mypy built-in types](https://mypy.readthedocs.io/en/stable/builtin_types.html),
[Python bool](https://docs.python.org/3/library/stdtypes.html#boolean-type-bool).

The list result is a reminder that generic compatibility follows variance,
not merely inheritance of element types. These probes establish checker behavior;
they do not implement Typeforge matching or settle every generic pattern rule.
Reproduction files: /tmp/typeforge-bool-compatibility/accepted.py and rejected.py.
Run each with .venv/bin/mypy --strict --no-incremental, .venv/bin/pyright, and
.venv/bin/pyrefly check --config pyproject.toml from the Typeforge checkout.

### Agreed mixed bare and whole-type selectors

```python
Map[int | str, int: bytes, Is[int | str]: float]
```

Agreed output: bytes-or-float. Ordered selection proceeds for each member. The
int member selects the first branch; str proceeds to the Is branch, which compares
the original whole subject int-or-str and succeeds. Reversing the branches:

```python
Map[int | str, Is[int | str]: float, int: bytes]
```

gives float because the first branch handles both members. This makes Is's
comparison subject stable rather than shrinking it to unhandled members, while
preserving first-match ordering for each member. Both outputs were confirmed by
the user. Explicit whole-type predicates mixed with distribution need derisking.

## D2 — Union equality

Expected behavior: Agreed. Unions use set equivalence, not tuple equivalence.

`Map[int | str, Is[str | int]: bytes, ...: float]` must produce `bytes`.
Reordering members or repeating an equivalent member does not change the union
type. This rule compares member types; it does not introduce subtype absorption
or decide Any behavior or alias transparency.

### Current implementation evidence

`Map[int | str, Equal[str | int]: bytes, ...: float]` produces `float` in the
compiler and `bytes` in runtime Schema evaluation (U08). With the same union
order on both sides, both produce `bytes` (U30).

Implementation still needs derisking. Preserve deterministic emitted ordering
independently of semantic equivalence, and exercise nested unions and unresolved
type parameters as well as resolved leaf types. This checklist item records an
agreed contract, not a completed implementation.

## D3 — Union aliases

Expected behavior: Agreed. In these cases, `type Numbers = int | str`.

Ordinary aliases are transparent for selection: the alias name is a binding
that expands to its underlying type. Substituting the alias body for its name
must preserve the selected output.

| Expression | Agreed output |
| --- | --- |
| `Map[Numbers, int: bytes, ...: float]` | `bytes \| float` |
| `Map[int, Numbers: bytes, ...: float]` | `bytes` |
| `Map[int, Assignable[Numbers]: bytes, ...: float]` | `bytes` |
| `Map[int \| str, Is[Numbers]: bytes, ...: float]` | `bytes` |

### Current implementation evidence

| Case | Expression | Current compiler / runtime Schema output |
| --- | --- | --- |
| U16 | `Map[Numbers, int: bytes, ...: float]` | `bytes | float` / `float` |
| U17 | `Map[int, Numbers: bytes, ...: float]` | `float` / `float` |
| U18 | `Map[int, Assignable[Numbers]: bytes, ...: float]` | `bytes` / `float` |
| U29 | `Map[Numbers, Numbers: bytes, ...: float]` | `float` / `bytes` |

NewType results are distinct from ordinary aliases and must not automatically
receive this transparency rule. Detailed NewType behavior is deferred; this
discussion does not authorize implementing it.

Implementation needs derisking around output metadata, Pydantic definition
identity, generic binding, and recursive aliases. Transparent selection need
not erase output aliases or bypass the current rejection of unsupported cycles.

## D4 — Any unions

Expected behavior: Output preservation and checker-compatible Any matching in
both directions are agreed. The latter supersedes earlier exact-only default
matching for Any. Assignable behavior is agreed if that helper remains public.
Any here means `typing.Any`.

### Agreed output preservation

`Map[int, int: Any | str]` produces `Any | str`. Typeforge must preserve the
explicit members rather than absorbing str into Any. The preserved type can
subsequently be compared with `Is[Any | str]` under set equivalence.

Downstream permissiveness does not justify erasing this distinction from
Typeforge's type representation. This decision does not require every checker
to retain the same display spelling.

### Agreed default subject matching — updated for compatibility

For `Map[Any | int, int: str, ...: bytes]`, retain both subject members and
produce str: both members are assignment-compatible with int. Preserve both
members in the subject representation even though their selected outputs coincide.
Accepting Any for the selector does not establish its concrete runtime type.

`Map[Any, int: str, ...: bytes]` produces str. This replaces the earlier bytes
outcome. Deterministic emitted order remains separate from set equivalence.

### Agreed Any selector behavior — updated for compatibility

Apply assignment compatibility when Any is the selector:

- `Map[int, Any: str, ...: bytes]` produces str.
- `Map[Any, Any: str, ...: bytes]` produces str.

`...:` remains the unconditional fallback. Is[Any] retains exact type comparison;
it is not replaced by compatibility matching.

### Agreed Assignable behavior

Assignable follows Python's assignment compatibility rules, including Any in
either direction:

- `Map[int, Assignable[Any]: str, ...: bytes]` produces str.
- `Map[Any, Assignable[int]: str, ...: bytes]` produces str.

Python's [typing documentation](https://docs.python.org/3/library/typing.html#the-any-type)
defines Any as assignable both to and from every type. This is static assignment
permission, not proof of a value's concrete runtime type. The agreed principle
is to extend Python's typing vocabulary without redefining its assignment
rules. These examples must not fall back or become indeterminate solely because
the source is Any. Default matching and Is retain their distinct meanings.

Derisk Any within union operands and unresolved generic provenance when
implementing this rule. Static comparison must not infer a runtime value from Any;
raw Input remains a separate controller.

### Current implementation evidence

- U24: `Map[Any | int, int: str, ...: bytes]` produces `bytes | str` in the
  compiler and `bytes` at runtime.
- U25: `Map[int, int: Any | str]` produces `Any | str` in the compiler and Any
  at runtime.

Derisk preservation through nested Maps and aliases and check assignment
compatibility against the agreed Python rules. Permissive validation alone
does not prove equivalent selection.

### Confirmed checker alignment for Any

The user approved following checker compatibility for Any. Positive assignment
and function-argument probes passed with mypy 2.2.0, Pyright 1.1.411, and Pyrefly
1.1.1 in both directions. The adopted changes are:

| Map | Superseded output | Agreed output |
| --- | --- | --- |
| `Map[Any, int: str, ...: bytes]` | bytes | str |
| `Map[int, Any: str, ...: bytes]` | bytes | str |
| `Map[Any | int, int: str, ...: bytes]` | str-or-bytes | str |

This is assignment permission, not evidence that Any is a known int. Is retains
exact comparison and explicit union preservation remains agreed. Probe source:
/tmp/typeforge-bool-compatibility/any_compatibility.py. No production matching
behavior was changed during this discussion.

### Generic compatibility examples — agreed

Follow checker variance for fully specified generic selectors:

```python
Map[list[bool], list[int]: str, ...: bytes]          # bytes
Map[Sequence[bool], Sequence[int]: str, ...: bytes]  # str
```

All three checked tools reject list[bool]-to-list[int] and accept
Sequence[bool]-to-Sequence[int]. These corresponding Map outcomes are agreed.
Capturing an unknown argument, such as list[Item], remains a separate structural
pattern operation; generic compatibility does not itself define capture inference.

### Capture through a compatible generic interface — agreed

```python
@type_function
def Element[T]():
    Item = Capture("Item")
    return Map[
        T,
        Sequence[Item]: Item,
        ...: bytes,
    ]
```

Agreed results:

| Subject | Result |
| --- | --- |
| `list[int]` | `int` |
| `list[bool]` | `bool` |
| `tuple[str, ...]` | `str` |
| `int` | `bytes` |

Match a compatible generic interface and bind its corresponding element type.
Capture preserves the actual element type rather than widening bool to int.
Repeated captures still require exact agreement; this proposal does not introduce
common-supertype inference. Generic interface projection and capture inference
need derisking in both compiler and runtime integrations before implementation.

### Capturing a union element type — agreed

Using Element above:

```python
Element[list[int | str]]  # int | str
Element[tuple[int, str]]  # int | str
```

For a heterogeneous fixed tuple, project its element types to their
union when matching Sequence[Item]. Preserve the known alternatives rather than
widening to object. Item occurs once in this pattern and captures one element
type, which may itself be a union. This does not relax the agreed exact-agreement
rule for repeated captures in tuple[Item, Item].

Union capture and heterogeneous tuple projection need derisking in both compiler
and runtime integrations. These are agreed Typeforge outcomes, not a claim that
all Python checkers infer the same type for an analogous generic function call.

## D5 — Union-valued fields

Expected behavior: Agreed. Both consumers must produce `value: bytes | float`.

For a TypedDict field `value: int | str`, a MapFields output using
`Field[Key, Map[Value, int: bytes, ...: float]]` currently emits a `float` field
through compiler record materialization; Pydantic produces `bytes | float`.
The compiler currently keeps the discovered field type opaque.

Moving the subject type into a field must preserve the same memberwise Map
selection already agreed for a directly authored union subject. This transforms
the field's type; it does not prescribe a conversion of input values.

Implementation still needs derisking for aliases, nested containers, inherited
fields, and speculative changes to field presence. The agreed value-type output
does not establish support for speculative field layouts. Copying a union field
and directly emitting union outputs already work.

## D6 — Callable precision

Expected behavior: Conservative projection fallback, known no-match handling,
conditional aggregate fallback, structural callable support, whole-type guard
verification, and accepted-input projection are agreed. Implementation feasibility
and verification coverage still need derisking.
Distinguish intended selection from
the precision that standard Python typing can represent.

### Agreed projection policy

For a callable returning `Map[T, int: str, ...: bytes]`, the latest compatibility
rules map both concrete int and bool subjects to str. Earlier exact-only examples
are superseded; Is remains available for exact whole-subject distinctions.
Those rules must not change merely because the result is projected as overloads.

If the compiler cannot faithfully express a distinction in standard typing,
the fallback is to widen the affected return to a sound possible-output
union (str-or-bytes here), retaining precise cases where representable. Do not
emit a narrower result that excludes an allowed output. This is an allowance
for established representation limits, not permission to skip available precision.

Prefer this conservative union fallback over a compilation error caused solely
by lack of exact precision. Improve precision wherever Typeforge can do better;
the fallback is a minimum guarantee, not a ceiling on supported precision.

Which concrete cases are representable still needs derisking with all supported
checkers, subclass overlap, unions, generic controllers, and implementation
verification. If no truthful standard output can be emitted, widening alone
does not resolve the unsupported relationship.

### No-default callable distinction — updated by D8

For `def convert[T](value: T) -> Map[T, int: str]: ...`, distinguish a known
semantic no-match from incomplete knowledge or limited checker projection:

- A concrete int subject selects str.
- A concrete str subject has no matching branch and fails Map evaluation under
  the later D8 decision. The earlier Never-only outcome is superseded.
- An unresolved subject may retain str as a possible normal output; exposing that
  bound does not prove that every input is accepted. Unresolved coverage and input
  contract projection still need derisking.

Preserve known no-match failures rather than applying the aggregate str fallback
indiscriminately. Conservative projection of possible outputs must not hide a
proven unsupported input. A Never return denotes no normal return; it does not
itself prohibit calling the function or implement runtime rejection. Input
contracts or targeted diagnostics must carry that rejection where required.

Current callable aggregate fallbacks can expose str even for unmatched calls
to this example. That limitation must not override the agreed semantic result.

### Agreed conditional aggregate fallback

For `def convert_many[T](*values: Each[T]) -> Collect[Map[T, int: str, ...: bytes]]: ...`,
assume generated overloads cover at most two arguments. Mapping concrete subject
types int, bytes, int has the semantic tuple output `tuple[str, bytes, str]`.

When the individual argument types are unavailable for matching, allow
`tuple[str | bytes, ...]`: every element retains the possible-output
bound, while position and length precision are lost. Keep the callable available
beyond the configured specialization limit, preserving the most precise supported
result. Increasing the limit may recover precision; it must not change selection.

The user's agreement is conditional on lacking the individual types. An arity
limit alone does not establish that those types are unknowable. If an integration
has enough type information and can represent the per-position mapping, retain
that precision rather than automatically taking the aggregate fallback.

This does not require emitting additional overloads based on consumer calls or
weakening known no-match results. Derisk the fallback with supported checkers;
the earlier precision decision still applies within specialized overloads.

Current generation for this exact example with maximum_arity=2 emits the fallback
`def convert_many[T](*values: T) -> tuple[object, ...]: ...`. Each positional
argument has type T, so the collected values tuple has type `tuple[T, ...]`.
The agreed `tuple[str | bytes, ...]` output would improve the current bound;
it is not the current emitted return type.

### Agreed structural callable support

For `def choose[T](value: T) -> Map[T, list[Value]: tuple[Value, ...], ...: bytes]: ...`,
support the following semantic outputs:

| Concrete subject | Agreed output |
| --- | --- |
| `list[int]` | `tuple[int, ...]` |
| `list[str]` | `tuple[str, ...]` |
| `bytes` | `bytes` |

The list element type should remain a reusable captured type, rather than
requiring enumeration of all possible element types. Current publication fails
with an unlowered MapValueType error. Implement support after derisking generic
overloads, subclass overlap, and the general fallback under the agreed precision
policy. This is static type capture, not runtime inspection of container values.

### Final callable decision batch — agreed 2026-09-30

#### Value guards do not change the original whole-type subject

```python
def encode[T](value: T) -> Map[T, Is[int]: str, ...: bytes]:
    if isinstance(value, int):
        return "integer"
    return b"other"
```

Reject this as a faithful implementation of the authored relationship
where supported verification can establish the violation. With T bound to bool,
Is[int] selects bytes, but the guard returns str. With T bound to int-or-str,
Is[int] also selects bytes; a narrowed integer value still reaches the str return.
The runtime guard narrows value, not the originally supplied type parameter.
For memberwise compatibility behavior, the intended annotation is instead
Map[T, int: str, ...: bytes]. Verification must not silently replace Is with that
different relationship. Detecting these cases generically, and faithfully
representing their calls in ordinary checkers, need derisking.

#### Missing defaults must preserve the accepted input contract

```python
def convert[T](value: T) -> Map[T, int: str]: ...
```

Known int/bool inputs select str; known str inputs fail under the agreed rules.
Represent the accepted input domain in the emitted signature when
possible. For this simple relationship, the intended portable signature is:

```python
def convert(value: int) -> str: ...
```

An object-typed value or unconstrained generic parameter cannot be assumed
covered merely because str is the only possible normal output. Delegate rejection
to the ordinary checker through the restricted parameter type. Preserve ordinary
Python Any compatibility; this is not a new strict-Any policy.

When coverage cannot be represented soundly at a supported boundary, issue a
diagnostic requiring an authored bound, specialization, or fallback rather than
publishing a signature that accepts every input. Keep unresolved templates legal
internally; this is an input-contract publication/checking policy, not an eager
error for every occurrence of an unresolved Map. Output precision loss with a
covered domain still follows the already agreed conservative union fallback.

Derisk input-domain projection, generic substitution, and compiler/runtime
failure boundaries. Runtime raw Input continues to use the separately agreed
validation-time no-match behavior.

The existing verification boundary continues to apply: generate precise
obligations for recognized flow, retain ordinary output-bound checks where the
dependency cannot be established, and make that coverage limitation explicit.
This batch does not promise a proof for arbitrary Python function bodies or add
a new Python type-inference engine.

### Guard verification and whole-subject predicates — historical open example

The example below predates removing Assignable. The final batch above presents
the remaining question with the agreed public Is spelling.

Consider `def encode[T](value: T) -> Map[T, Assignable[int]: str, ...: bytes]`
whose body returns str inside `if isinstance(value, int)` and bytes otherwise.
For concrete int or str subjects, those paths appear to agree with selection.
For a subject T of int-or-str, however, whole-subject Assignable[int] is false
under D1, so the selected output is bytes even when the actual value is an int.

A runtime guard can narrow the value without proving that the original complete
subject T is assignable to int. Therefore the earlier guard limitation must be
investigated against the agreed contract rather than automatically removed as
a false positive. Proposed outcome, not yet agreed: flag a str return when the
subject's selected output is bytes; do not silently distribute whole-subject
predicates to make the implementation pass.

Derisk generic binding, union call subjects, and which facts verification can
establish. The existing conservative projection policy must not be used to hide
an implementation that violates a known semantic output.

### Current limitations to resolve

- `Map[T, All[Assignable[int], Not[Equal[bool]]]: str, ...: bytes]` currently
  gives a call with `1` the checker type `str | bytes`; a call with True gets
  bytes. Agree on selection and the permitted fallback when precision is lost.
- An overload parameter typed int also accepts bool. Decide how exact Map
  selectors should be represented when overload subtyping cannot encode them.
- Assignable with an isinstance guard can leave verification requiring the
  fallback output inside the guarded return. Agree on supported narrowing.
- Each/Collect specialize only to the configured arity; calls beyond the finite
  frontier retain aggregate outputs, including for Maps without a default.
- Unbounded structural callable outputs such as `list[Value]` can fail emission.
  Decide which forms must be supported and which should remain explicit errors.
- Base-first record overloads can shadow derived-record overloads. Agree on
  selection order and how to preserve it in emitted interfaces.

See the [publication contracts](../../tests/unit/compiler/pipeline/test_slice_publication.py),
[overlay contracts](../../tests/unit/overlay/test_inline_maps.py), and
[field contracts](../../tests/unit/test_slice_fields.py).

## D7 — Unsupported union structures

Expected behavior and support scope: Record-union transformation, failure on known
unsupported members, unambiguous capture-pattern unions, and overlapping capture
outputs are agreed. Implementation derisking remains; record metadata is tracked
separately under F1.

### Unsupported member in a record union — agreed

Given a supported User TypedDict and the agreed Public type function:

```python
Public[User | int]  # error: Fields cannot inspect int
```

Fail the complete application when Fields encounters a known
unsupported union member. Do not silently discard that member or treat it as an
empty record. This follows the agreed principle that a known unsupported input
must not disappear from a successful result. The compiler should report the
authored application and offending member; concrete runtime schema construction
should fail as well. This does not prescribe evaluation of unresolved T.

Derisk unsupported-member failure propagation through record unions in both
compiler and runtime integrations.

### Agreed record-union support

Transform each supported TypedDict alternative independently and retain a union
of the resulting record shapes. For A with fields x:int and y:str, and B with
fields x:bytes and y:float:

```python
type Listed = MapFields[A | B, Field[Key, list[Value]]]
```

Agreed output: ListedA-or-ListedB, where ListedA has x:list[int], y:list[str]
and ListedB has x:list[bytes], y:list[float]. Do not merge corresponding fields
into independent unions: that would admit combinations from different source
alternatives, losing their correlation.

Add support for these record-union operands, which currently fail. Unsupported
members fail under the agreed rule above; no new record family is implied. Derisk record
metadata, generics, overlap, naming, and Pydantic union behavior before
implementation. Keep unions of structural capture patterns as a separate decision.

### Agreed unambiguous capture-pattern union

```python
type Element[T] = Map[T, list[Value] | set[Value]: Value, ...: bytes]
```

Treat these selector members as alternative structural patterns. When exactly
one alternative matches, use its Value capture in the output:

| Concrete subject | Agreed output |
| --- | --- |
| `list[int]` | `int` |
| `set[str]` | `str` |
| `dict[str, int]` | `bytes` |

Add support for the currently rejected pattern union. Each example
has a concrete non-union subject and no overlapping successful captures, so
agreement does not decide subject distribution or conflicting captures. Branch
ordering remains separate from the order-independent union of patterns.

### Overlapping captures — resolved after binding-syntax review

This proposal was paused for a syntax review and subsequently approved using
named captures; see the
[agreed ambiguity behavior](#agreed-conflicting-captures-across-alternatives).

```python
Map[
    tuple[int, str],
    tuple[Value, str] | tuple[int, Value]: tuple[Value, Value],
    ...: bytes,
]
```

Both alternatives match: the first captures int and the second captures str.
Agreed output: `tuple[int, int] | tuple[str, str]`. Evaluate the branch output
separately for each successful capture, then union those complete results.
Merging captures before substitution would produce `tuple[int | str, int | str]`,
which admits mixed pairs that neither alternative produces. Choosing the first
successful union member would make meaning depend on union order.

This proposal preserves ordered Map branches while treating alternatives within
one selector union as unordered. It uses a concrete non-union subject and does
not decide subject distribution. Derisk overlapping pattern matching and capture
substitution before implementation; unbound captures and invalid outputs remain
separate cases.

### Current implementation evidence

- `MapFields[Row | Other, Map[Key, ...: Field[Key, Value]]]` is rejected.
- `Map[list[int], list[Value] | set[Value]: Value, ...: bytes]` is rejected.

Record alternatives and overlapping capture outputs are agreed above; remaining
branch interactions and metadata need decisions or derisking before implementation.
Supporting unions does not implicitly add new record families.

## Reopened — Binding syntax

The user requested a broader review of Key and Value before deciding overlapping
capture behavior. Existing Value has two roles: current field type and structural
capture. Evaluation prefers a capture over the field type, and the shared context
stores only one structural capture. Repeated captures currently require equality;
they do not represent independently named type arguments.

The user likes explicit named bindings as a direction. Exact declaration syntax
and binding rules remain exploratory. Two directions considered:

- Separate contextual field references from named pattern captures. Names such
  as FieldName and FieldType clarify context but retain implicit field binding.
- Let authors declare reusable capture tokens, then bind field names and types
  explicitly using a slice. This also supports multiple independent pattern
  captures and distinguishing outer field context from inner captures.

Candidate spelling for the second direction:

```python
Name = Capture("Name")
Kind = Capture("Kind")
Item = Capture("Item")

type Element[T] = Map[T, list[Item]: Item, ...: T]
type Listed[T] = MapFields[T, (Name, Kind): Field[Name, list[Kind]]]
type Unwrapped[T] = MapFields[
    T,
    (Name, Kind): Field[Name, Map[Kind, list[Item]: Item, ...: Kind]],
]
```

Capture is a proposed inert declaration, not a current API. Tokens identify
bindings local to an evaluation, not mutable global state or caller-supplied type
parameters. Declaration identity, nesting and shadowing, alias substitution,
reuse, and unbound-reference diagnostics need design and derisking. Named
bindings clarify which captured type an output references; they do not resolve
multiple successful matches by themselves.

The explicit MapFields slice parses as Python. Runtime annotation compatibility,
compiler declaration discovery without executing authored code, and checker
projection have not been prototyped. Multiple captures would require extending
the shared binding representation, not only changing AST normalization. Retain
field names as a distinct semantic role from typing types.

### Type-function scope — direction agreed, details pending

The user likes the proposed type-function approach. Exact spelling, supported
body forms, and runtime construction remain to be designed and derisked.

The user asked whether a scope returning a type could keep capture declarations
local and let complex definitions span multiple statements. Candidate syntax:

```python
@type_function
def Public[T]():
    Name = Capture("Name")
    Kind = Capture("Kind")

    type PublicField = Map[
        Name,
        Literal["password"]: Drop,
        Literal["name"]: OptionalField[Literal["display_name"], Kind],
        ...: Field[Name, Kind],
    ]

    return MapFields[T, (Name, Kind): PublicField]

type PublicUser = Public[User]
```

Proposed meaning: a generic type definition with local scope, used through type
subscription. Locals describe reusable expression templates; defining PublicField
does not evaluate its captures before the enclosing MapFields binds them.
MapFields still owns iteration over record fields; a type function supplies scope
and composition. Removing MapFields or adding field-loop syntax is not decided.

Start by considering a restricted straight-line body: capture declarations,
local type aliases, and one final return of a type expression. Arbitrary Python
calls, control flow, mutation, and I/O are outside this initial proposal.
The compiler would parse and lower the body without executing it. One possible
runtime counterpart constructs a symbolic template once from the body, then
specializes it through existing evaluation; this is an architectural option, not
an implemented decorator or a decision to execute arbitrary user functions.

Derisk runtime template construction without requiring source files, generic
parameter identity, local alias/capture scope, lazy evaluation, recursive
definitions, and projection as ordinary typing declarations. Type functions do
not increase the relationships representable by existing checkers. Named bindings
already require shared model changes; preserving local definitions as reusable
templates may require additional representation changes beyond AST parsing.

### Preferred field authoring — record comprehensions

With type-function scope accepted as a direction, the user asked whether MapFields
should remain and whether its syntax can be simplified. The user selected the
Record/Fields comprehension below as the preferred authoring direction. Field
traversal and record reconstruction remain necessary operations regardless of
their public spelling. The first decision batch now approves removing MapFields
authoring at a breaking cutover without migration guides. After the successful
POC, the user confirmed this as the goal API and
explicitly deferred implementation until the syntax and semantics are settled.

The earlier callback alternative, not selected, replaces explicit name/type
capture declarations with one local symbolic field parameter:

```python
@type_function
def Public[T]():
    return MapFields[T, lambda field: Map[
        field.name,
        Literal["password"]: Drop,
        Literal["name"]: OptionalField[Literal["display_name"], field.type],
        ...: field,
    ]]
```

The lambda describes a field transform. The compiler parses its expression;
it does not execute it. A runtime constructor could apply it to a symbolic field
descriptor to build a template. This would extend the proposed supported body
forms with a constrained callback expression, not arbitrary Python callbacks.
Returning field proposes preserving the original field, including modifiers and
metadata. Explicit Field/OptionalField/ReadonlyField constructors retain their
existing modifier-setting semantics. This distinction is not yet agreed.

The selected direction uses a record comprehension:

```python
@type_function
def Public[T]():
    return Record(
        Map[
            field.name,
            Literal["password"]: Drop,
            ...: field,
        ]
        for field in Fields[T]
    )
```

The intended reading is: inspect the fields of T, transform each field with Map,
and build the resulting record. The comprehension binds field locally; field.name
and field.type replace ambient Key/Value references for this operation. This does
not settle named structural-capture syntax or overlapping capture behavior.

Both spellings parse as Python. The selected comprehension now has a successful
[bounded prototype](record-comprehension-poc.md); the callback alternative remains
unprototyped. The selected comprehension requires a deliberate symbolic iteration
model when T is unknown; ordinary Python iteration does not provide that automatically.
The initial proposal expands the straight-line type-function subset with this
specific comprehension form, not general Python control flow.

POC targets and continuing implementation checks:

- Compiler lowering without executing authored code, with diagnostics mapped to
  the authored comprehension.
- Runtime template construction without requiring authored source files, including
  unresolved T, deferred evaluation, and specialization without exhausting or
  sharing one-shot generator state.
- Preservation of independent record alternatives for A-or-B. Fields must not
  flatten alternative records into one field stream. Union behavior needs derisking.
- Record output family, metadata, and modifier preservation when returning field;
  precise rules are still pending. No new supported record families are implied.
- Reuse of the field-transform evaluator and ordinary checker projections, with
  explicit identification of any additional binding or template data required.

## F1 — Field passthrough and edits

Field passthrough, property-preserving edits, and the field.replace spelling are
agreed as a design direction. The user sees this as a useful field extension point
and confirmed that a Drop produced as the replacement type removes the field.
Mixed union outcomes and other replacement arguments remain open.

Agreed rule: returning field preserves it; an explicit field edit changes only
the requested properties. Changing its type preserves its name, requiredness, and
readonly status. Renaming preserves its type and those flags. No in-place mutation
of the source field is implied.

Agreed authoring direction:

```python
@type_function
def AsBytes[T]():
    return Record(
        field.replace(type=bytes)
        for field in Fields[T]
    )
```

For nickname:NotRequired[ReadOnly[str]], agreed output is
nickname:NotRequired[ReadOnly[bytes]]. A field.replace operation would require
explicit support in the restricted type-function language; arbitrary method calls
are not implied. It has not been prototyped.

Type-attached metadata follows the agreed replacement rule below: replacing the
type replaces its complete annotation. Record-level metadata remains separate.
The new-field constructor surface remains a separate decision. The first batch
approves replacing superseded constructors at the unreleased library's cutover.

### Agreed Drop-consuming replacement and local generic alias

The user confirmed that Drop produced while evaluating a replacement type removes
the whole field. They prefer factoring that expression into a local generic alias
for readability; this is part of the intended type-function syntax:

```python
@type_function
def WithoutIntegers[T]():
    type DropCondition[A] = Map[A, int: Drop, ...: A]

    return Record(
        field.replace(type=DropCondition[field.type])
        for field in Fields[T]
    )
```

Agreed scalar examples: count:int is removed; label:str is retained with its
existing name and modifiers. This consumes a field-control result after
evaluating the replacement expression, not treat Drop as an ordinary value type.
Its meaning is distinct from explicitly setting a field's value type to Never.
Local generic aliases require lexical parameter binding and substitution before
evaluating the replacement. The earlier POC only tested local non-generic selector
aliases; it does not prove this expanded body form or field.replace support.

### Agreed partial-union drop versus Is

For count:int, label:str, and value:int-or-str, the user expects:

| Local DropCondition selector | count | label | value |
| --- | --- | --- | --- |
| `int: Drop` | removed | str | removed |
| `Is[int]: Drop` | removed | str | int-or-str |

The fallback in both aliases is `...: A`. A matching bare int member is sufficient
to remove the whole union-valued field. Is[int] compares the whole field type,
so it does not remove int-or-str. This reaffirms whole-subject Is for this case;
reconcile it with the broader reopened distribution discussion before implementation.

For mixed successful replacement outcomes, the Drop result must not be discarded
as if it were Never. Proposed ownership: field replacement consumes the removal
effect rather than changing ordinary Map output-union rules. Detailed representation,
indeterminate/speculative outcomes, and Drop in other arguments remain open.
This union behavior needs derisking; the earlier POC does not exercise field.replace.

### Agreed generic parameter references during distribution

Type parameters retain their supplied arguments during memberwise matching.
Distribution does not rebind references to the enclosing alias parameter. For:

```python
type WrapOther[A] = Map[A, int: bytes, ...: list[A]]
```

the agreed output for WrapOther[int-or-str] is bytes-or-list[int-or-str]. This
preserves transparent alias substitution: A still denotes the original union.
Captures separately name types discovered while matching. The agreed direction
for an explicitly member-specific output is:

```python
@type_function
def WrapOther[A]():
    Item = Capture("Item")

    return Map[
        A,
        int: bytes,
        Item: list[Item],
    ]
```

Here the final capture pattern binds remaining subject members, giving
bytes-or-list[str] for int-or-str. A remains the original argument if referenced
elsewhere in the output. Changing selector matching scope does not change the
meaning of references to A. This is a design decision, not prototype coverage.
Derisk parameter/capture identities and union distribution during implementation.

### Agreed repeated capture within one pattern

```python
@type_function
def SamePair[T]():
    Item = Capture("Item")

    return Map[
        T,
        tuple[Item, Item]: Item,
        ...: Never,
    ]
```

Agreed rule: occurrences of one capture within a single pattern must agree on
the same type; they do not accumulate a union or overwrite each other. Agreed
outputs: tuple[int, int] gives int; tuple[int, str] and tuple[int, bool] give Never.
Use the agreed type-equivalence rules, including order-independent union equality,
when checking consistency. Independent positions use different capture names.
Repeated captures across alternative patterns and nested scopes remain separate
decisions. Union-valued captures need derisking.

### Agreed conflicting captures across alternatives

Return to D7's overlapping pattern-union case using explicit named captures:

```python
@type_function
def Repeated[T]():
    Item = Capture("Item")

    return Map[
        T,
        tuple[Item, str] | tuple[int, Item]: tuple[Item, Item],
        ...: Never,
    ]
```

For Repeated[tuple[int, str]], both alternatives match, but the first binds Item
to int and the second to str. The user explicitly accepts both bindings: evaluate
the output independently for each successful alternative, then union the complete
results. Agreed output: tuple[int, int]-or-tuple[str, str]. Do not merge Item into
int-or-str before substitution, which would admit mixed pairs. An ambiguity error
for these conflicting successful bindings was considered and not selected.

Repeated occurrences within each individual alternative must still agree under
the previously accepted rule. Different successful alternatives have separate
binding environments; they need not agree with each other.

If priority is intended, separate ordered Map branches express it explicitly:

```python
Map[
    T,
    tuple[Item, str]: tuple[Item, Item],
    tuple[int, Item]: tuple[Item, Item],
    ...: Never,
]
```

For the same concrete subject, the first branch gives tuple[int, int]. A union
selector has no member priority. Unknown subjects and missing captures remain
separate design questions. Derisk overlapping union patterns before implementation.

### Agreed missing capture on a matched alternative

With a declared Item capture, consider:

```python
Map[int, list[Item] | int: Item, ...: bytes]
```

The int alternative matches but does not bind Item, which its output requires.
Agreed outcome: an unbound-capture diagnostic. A matched alternative with an
invalid output does not become a no-match and does not select the bytes fallback.
This concrete case does not decide whether all potentially missing bindings must
be rejected at definition time, before a concrete subject is available. Union
alternatives and scope/binding analysis need derisking.

### Initial unbound-capture diagnostic timing

```python
@type_function
def Element[T]():
    Item = Capture("Item")

    return Map[
        T,
        list[Item] | int: Item,
        ...: bytes,
    ]
```

The user delegated timing to whichever is easiest for the initial pass. Selected
approach: detect the missing binding when semantic evaluation needs the capture,
using the existing evaluation failure boundary. Do not add a mandatory separate
definition-time capture analysis pass. A concrete Element[int] evaluation reports
an unbound Item instead of falling through to bytes.

This is not runtime-only checking: compiler evaluations can report the same error.
Nor does it promise that an unevaluated declaration is always accepted by every
compiler projection. Earlier definition-time diagnostics may be added later;
speculative unresolved evaluation and generic reachability need separate care.

### Agreed capture reuse in nested Maps

```python
@type_function
def Nested[T]():
    Item = Capture("Item")

    return Map[
        T,
        list[Item]: Map[str, Item: bytes, ...: float],
        ...: Never,
    ]
```

For Nested[list[int]], the outer pattern binds Item to int. Agreed behavior:
the inner selector refers to that existing binding and therefore does not match
str; output is float. Do not silently recapture str under the same token. A fresh
capture declaration/name would express independent inner capture. This follows
stable binding reuse. It has not been prototyped.

Separately preserve independent binding environments for union alternatives and
Map evaluations; nested reuse does not merge those environments.
Failed patterns must not leak partial bindings into later alternatives or defaults.
The isolation rule is agreed in the concrete example below.

### Failed-pattern capture isolation — agreed

With a declared Item capture:

```python
Map[
    tuple[int, str],
    tuple[Item, int]: bytes,
    tuple[int, Item]: Item,
    ...: float,
]
# str
```

The first pattern can bind Item to int while examining the first position, but
fails at the second position. Discard that tentative binding. The second branch
starts with the original incoming environment and binds Item to str. Retain any
bindings established by an enclosing successful match; only bindings introduced
by the failed attempt are discarded. This makes the outcome independent of the
order in which a pattern's components are examined.

### Agreed replacement of type-attached metadata

The user confirmed the metadata rule deferred when field.replace was introduced.
Agreed rule: field.type includes its Annotated metadata. Replacing type
replaces that complete annotation; retaining or embedding field.type retains
the metadata at its original type position. Field name, requiredness, and readonly
status remain separate properties preserved by an edit unless explicitly changed.

For a source field label:NotRequired[Annotated[str, MaxLen(10)]]:

| Edit | Agreed field type |
| --- | --- |
| `field.replace(type=int)` | `NotRequired[int]` |
| `field.replace(type=list[field.type])` | `NotRequired[list[Annotated[str, MaxLen(10)]]]` |
| `field.replace(name="title")` | `NotRequired[Annotated[str, MaxLen(10)]]`, under the new name |

MaxLen here is example type-attached constraint metadata. The wrapping example
retains it on each string element; it does not move the constraint onto the list.
This rule does not decide record-level metadata or introduce a separate field
metadata editing API. Compiler projection may not express every runtime metadata
constraint; runtime consumers retain their existing metadata interpretation.

## D8 — No-match and Never

Expected behavior: Uncovered members fail the whole Map; ordinary Never union
semantics are preserved. Explicit Never outputs and propagation through enclosing
unions are agreed. Runtime selected-output failures do not retry selection;
unmatched raw inputs fail at validation, and known uncovered static subjects fail
schema construction. These concrete D8 decisions are complete; implementation
and unresolved generic coverage still need derisking.

### Agreed partial static no-match failure

```python
type Result = Map[int | str, int: bytes]
```

The user rejected resolving this example to bytes because str is outside the
mapping's accepted contract. After discussing Python compatibility, they approved
an uncovered member failing the whole Map while ordinary explicitly authored
Never unions retain Python semantics. The earlier suggestion to make Never
annihilate ordinary unions was not selected as the final approach.

This preserves the goal of delegating ordinary checking to Python checkers.
Python Never denotes an empty
set of values, so ordinary T-or-Never is equivalent to T, and a Never return
annotation means no normal return rather than a prohibited call. Sources:
[special types](https://typing.python.org/en/latest/spec/special-types.html#never),
[union semantics](https://typing.python.org/en/latest/spec/concepts.html#union-types).

Agreed rule: make an uncovered member a failed Map
evaluation, retaining the no-match fact before ordinary union simplification.
Report the missing str case directly; reject schema construction for that failed
expression. Preserve ordinary Python Never semantics for explicitly authored
Never types. If callable inputs must be rejected, encode that contract in input
annotations where representable or issue a targeted diagnostic; merely emitting
a Never return is insufficient. This supersedes the earlier D6 Never-only outcome
for known unmatched callable subjects; representable input contracts still need
derisking.

No implementation change has been authorized during this design discussion.

### Agreed explicit Never and enclosing-union examples

```python
Map[int | str, int: Never, str: bytes]
# bytes, without a missing-case error.

Map[int | str, int: bytes] | float
# Missing str case error; float does not rescue the failed Map.
```

In the first example every subject member has an explicit branch; Never denotes
no normal output from the int branch. In the second, Map evaluation fails before
there is a successful type value to union with float. Do not convert that failure
to ordinary Never and simplify it away. Both outputs were explicitly confirmed
by the user. The same distinction implies bytes for U21, str for U22, and an error
for U23 below; these are consequences of the agreed rules, not new runtime tests.

### Agreed runtime selected-output failure

```python
Schema[Map[Input, int: Literal[0], ...: object]]
```

Input is the runtime-input marker. Agreed behavior for an incoming 7: select
the int branch, then reject the value because it does not satisfy Literal[0].
Do not retry the object fallback, even though it would accept 7. Selection commits
to a branch before validating its output. An incoming 0 succeeds on the int
branch, and an incoming string selects the object fallback directly.

This confirms the existing runtime rule independently of the new
static no-match policy. Exhausting a value-time Map without a fallback remains
a separate validation-error case to confirm.

### Agreed no-match failure phase

```python
Schema[Map[Input, int: int]]
```

Agreed behavior: schema construction succeeds, because the subject is supplied
later by an incoming value. An incoming 7 selects the int branch and validates;
an incoming "hello" has no branch and raises a validation error. No fallback is
required merely because other possible incoming values would be unsupported.

In contrast, Schema[Map[str, int: int]] fails during schema construction: str is
already a known unsupported subject. Likewise, an uncovered member of a known
static union fails construction under the agreed rule. This phase distinction
does not turn unresolved generic parameters into Input; static uncertainty and
raw-value selection remain distinct.

### Current implementation evidence

- U04: `Map[int | str, int: bytes]` produces bytes statically, but runtime Schema
  construction rejects the unmatched str path.
- U23: `Map[int, str: bytes] | float` produces float statically, but runtime
  Schema construction rejects the reached no-match.
- U21: `Map[int | str, int: Never, ...: bytes]` produces bytes in both consumers.
- U22: `Map[int, int: Never] | str` produces str in both consumers.

An unmatched raw Input currently raises a validation error. A selected output
validation failure does not retry later branches. Both runtime rules are now
confirmed separately from static union simplification and schema-build failures.
