# Typeforge Design

Typeforge is an authoring layer and compiler for Python typing. It targets existing type checkers rather than replacing them.

## Principles

- Authored source remains valid Python.
- Runtime markers are inert and add no overhead to application call paths.
- The compiler parses source without importing or executing user code.
- Generated output uses standard typing constructs understood by existing checkers.
- Diagnostics refer to authored source rather than generated implementation details.

## Complete interfaces

A `.pyi` file replaces its corresponding implementation as the module interface seen by a type checker. Typeforge must therefore preserve the complete public interface of every module it shadows. If it cannot safely preserve a declaration, generation must fail instead of silently omitting it.

## Honest expressiveness

Some relationships can be expressed directly with standard generics. Others can only be lowered over known types, literals, fields, or argument counts.

Finite specialization must remain explicit. Typeforge should provide a documented fallback, require local specialization, or report that a relationship cannot be represented portably. It must not present a configured finite frontier as an open-ended generic capability.

## Unified type mapping

The public runtime `Map` constructor normalizes subscription slices into the
canonical Map/Case/Default aliases in `_markers` before Python discovers or
substitutes generic parameters. `_map` owns construction; it does not evaluate
relationships or expand authored aliases. Frontends recognize canonical marker
identity rather than the public constructor. The typing-only public export retains
the conservative object alias; raw slices still require checker projection.
Public subscriptions require slice branches; `Case` and `Default` are private
data aliases. Compiler normalization and runtime frontend tests construct those
internal aliases directly to verify representation parity and malformed-data
failures. They are not a public compatibility path.

`Map` is Typeforge's central input/output type machine. Its ordered `selector: output`
branches accept compatible types, structural patterns, or exact `Is[Type]`
selectors; the first matching branch selects the output. `...: output`
handles the unmatched path. With no fallback, a known uncovered subject fails the
whole Map, including when it appears inside another union or type application.
An explicitly selected `Never` retains ordinary Python union simplification.

Scalar bare matching follows Python assignment compatibility, including class
inheritance, bool/int, numeric widening, and Any. Compiler adaptation carries
local class ancestry and alias facts from the source snapshot to Schema lowering.
`Is` lowers to existing exact equality data. Structural patterns bind explicit
Capture tokens. Record comprehensions bind a lexical field whose `.name` and
`.type` refer to the current field; the field itself preserves the complete entry.
Equal/Assignable/All/Any/Not remain private semantic
representations for existing internal consumers; they are not public authoring.

Known union subjects select each member independently in branch order. Exact
`Is` selectors always compare the original whole subject; preceding branches do
not shrink it. Union equality ignores order and duplicates, including inside
parameterized types. Comparison does not reorder emitted unions.

Shared semantic evaluation distinguishes runtime `Input` from unresolved static
type identity. A deferred Map preserves selection until input is available;
unresolved static comparisons instead produce true, false, or indeterminate.
Same-symbol identity and known structural positions remain meaningful. At an
indeterminate case, only its output and the reachable remainder contribute to the
possible output type. Nested results retain their provenance so a possible union
is not mistaken for a definitely selected type.

`Evaluator` owns traversal and ordered Map selection, composed with `TypeSystem`
for type operations and `EvaluationPolicy` for consumer acceptance decisions.
Expressions and outcomes remain data. Each evaluator binds a read-only, immutable
`EvaluationContext` carrying bindings and definite/speculative reachability.
`with_context` creates a child sharing the type adapter and policy; it never
temporarily replaces the parent's context. Ordinary recursive calls use the bound
context, while field bindings, captures, and speculative paths use derived child
evaluators. Parent and sibling evaluations remain independent, including after
failures and during reentrant evaluation.

Runtime consumers can compose the evaluator with `DeferredTypes` to represent a
deferred Map as a backend type. This preserves execution plans through ordinary
type construction, annotations, and fields. Such plans do not require a static
output bound; compiler evaluation continues to compute that bound when no
deferred type adapter is supplied. Backend adapters consume shared plans rather
than introducing another expression evaluator.

`Evaluator.select_deferred_map` resumes a deferred plan with a backend input type
and an `InputObserver`. The observer owns raw leaf observations; shared semantics owns
predicate evaluation, short-circuit composition, case order, and defaults. The
result retains the selected expression, case/default identity, and bound context
before any output validation. Raw values and validators stay outside shared
semantic data. A validation failure cannot resume case selection.

Expression families use separate named `singledispatchmethod` handlers on the
evaluator. A small typed recursive entry point preserves the backend type
parameter across the dispatch descriptor; individual operators remain local
rather than accumulating in one conditional traversal method.

An exhausted Map produces a `MapNoMatch` fact retaining its original expression,
evaluated subject, and context. Policy returns `NoMatchDecision.ACCEPT` or
`REJECT`; rejection stops evaluation and returns that fact as a declared failure
alongside ordinary `SemanticIssue` failures. Explicit case/default outputs of
Never do not invoke no-match policy. Integration code translates failures using
its authored source information; expected integration exceptions do not escape
through semantic callbacks.

Indeterminate branches, their reachable remainders, deferred output bounds, and
conditions following an indeterminate short-circuit operand are speculative.
That mode propagates through nested expressions even when their own subjects are
concrete. The shared default policy accepts speculative no-match bounds and
rejects reached no-match paths. Compiler and Pydantic consumers use that policy;
unrelated semantic errors still propagate. The convenience
`evaluate(expression, type_system)` returns `SemanticIssue | MapNoMatch` failures.
Compiler schema and record boundaries translate no-match facts into authored
diagnostics once, rather than converting them to a selected Never type.

Compiler semantic lowering keeps field-name expressions distinct from typing
types and output templates. A string Literal can name a transformed field while
remaining an ordinary typing Literal in that field's type. Output-template roles
compose through unions and parameterized arguments, preserving scoped field
bindings. Production Schema boundaries evaluate through shared semantics,
including deferred Input bounds and unresolved static type identity.

The compiler's source schema adapter expands authored aliases before shared
lowering, keeping callable relationship IR separate. It requires the source
snapshot's alias context and preserves omitted defaults and authored cycles.
The same expansion owner resolves predicate aliases for callable adaptation and
record materialization. Record adaptation also expands ordinary field aliases
when a Map needs field type facts; passthrough retains its existing alias policy.
Record materialization receives parsed class ancestry through the semantic
environment used for both original fields and transform selectors.
After expansion, each Map binds unary selector predicates to its own subject via
the source selector normalizer, before binary arity validation. Predicate alias
declarations remain unbound templates with a bool fallback in emitted interfaces.
Static type emission is shared with record materialization; schema origins follow
normalization without merging independent boundary roots. Production declaration
adaptation and reusable Schema roots both use this adapter. Callable Map
relationships retain their overload path; record aliases retain their existing
materialization stage, and Each/Collect retain finite specialization.

Record alias traversal belongs to `RecordAliasRewriter`, configured once with
derived records and a rewrite observer. Its declaration and type operations reuse
the shared stub-IR tree rewriter; recursive declaration methods retain their
configuration without forwarding observer arguments. Adaptation owns authored
origin tracking and supplies the observer when constructing the rewriter.
Concrete record applications retain expression origins before materialization.
Adaptation expands each application through the existing source alias owner and
evaluates its complete argument with visible record facts. Equal outputs reuse
the same alias/source specialization; changed outputs get deterministic names
that avoid authored declarations. The rewriter consumes these application
replacements alongside ordinary scalar replacements. Unresolved callable type
parameters retain their existing finite specialization path.

The runtime frontend carries an explicit selector subject through predicate
aliases, compound conditions, and Annotated wrappers. Nested Maps establish a
new subject; output types and explicit predicate operands receive no implicit
subject. Alias type parameters retain their existing identity-based bindings.
Literal normalization is shared with construction. Neither frontend stores
implicit predicates in shared semantic data or changes union matching policies.

Runtime `_selection_type` expands ordinary aliases in subjects, selectors, and
outputs consumed by a surrounding Map. It reuses alias argument binding and
cycle detection, resolving supplied arguments before entering the alias body so
finite repeated applications are not mistaken for recursion. Child bindings are
independent; TypeVar annotations retain their generic provenance. Ordinary selected
output aliases still delegate metadata, references, and recursion to Pydantic.
The runtime union builder flattens and deduplicates in encounter order without
absorbing explicit members beside Any, preserving later whole-type comparisons.

Resolved fixed generic selectors use assignment compatibility rather than capture
matching. Shared generic policy receives backend-neutral GenericType facts:
list/set/dict are invariant, Sequence/frozenset/tuple are covariant, and Mapping
keys are invariant while values are covariant. Lists and tuples can match
Sequence; dict can match Mapping. Mutual assignment in invariant positions keeps
Python's gradual Any rule. Native origins and unsupported facts stay behind
TypeSystem adapters; imported generic identity is separate from emitted spelling.

This is a finite frontier. Different arguments for an unknown generic origin
produce a typed diagnostic, including when a fallback exists. Identical types
can still match without requiring variance facts. Partially known shapes retain
their structural proofs and provenance; broader variance reasoning for unresolved
parameters belongs to the callable precision slice.

Pydantic diagnostic display reconstructs slice branches from canonical typing
arguments without expanding aliases or interpreting Literal/Annotated payloads.
Issue data, codes, phases, and validation locations stay unchanged; display does
not add authored-state storage to the runtime constructor or semantic evaluator.

## Reusable type functions

The public type_function decorator constructs a template once during an ordinary
Python import. It returns an immutable TypeAliasType with the function's original
type parameter identities. Closure cells for those parameters are replaced in a
construction-only function copy by immutable GenericAlias bridges; the authored
function and unrelated closure cells are not mutated. These symbols reject
truthiness. Map annotations reject truthiness too. Specialization uses existing
alias binding and shared evaluation rather than replaying the construction body.
The base constructor depends only on the standard library; Schema remains the
optional Pydantic evaluation boundary.

Alias creation uses the authored globals for Python's native module identity,
executing only Typeforge's factory code in that namespace. Unrelated closure cells
remain lazy, including cells whose values have not been assigned at construction.

Runtime accepts ordinary construction code that returns a valid typing template.
It validates the returned structure, keeps Literal payloads and Annotated metadata
opaque, and rejects foreign unbound parameters. Unexpected application exceptions
propagate unchanged. Compilation, source access, and saved artifacts are optional.

The compiler recognizes the decorator by resolved import identity and turns a
supported return expression into a Source TypeAliasDeclaration, retaining its
authored span and a type-function distinction. Existing schema alias expansion,
cycle checks, semantic lowering, evaluation, and emission own specialization and
output bounds. Type functions do not enter the legacy callable relationship alias
path. Generated interfaces contain standard type aliases and specialized usages.

The basic compiler frontier is a module-level synchronous function with no value
parameters, no other decorators, unconstrained ordinary type parameters without
defaults, an optional docstring, capture declarations, local type aliases, and one
final return of a
typing expression.
Supported expressions include Map, Is, unions, generic types, and subscription of
other type functions. Unsupported source produces authored diagnostics without an
execution fallback. Record supports one unfiltered generator over Fields with a
single name binding.
Runtime acceptance of extra
Python construction statements does not imply compiler support.

Local aliases retain qualified lexical names, type parameters, and authored spans
in the source model. Their unconstrained ordinary parameters shadow enclosing
parameters and capture bindings. The compiler requires explicit alias arguments.
Source adaptation expands local aliases before binding outer parameters, then
expands type-function composition before classifying record templates. Existing
alias expansion owns substitution, arity checks, selector binding, and cycles.
Capture and field declaration identities survive expansion. Local aliases emit
no independent public declarations.

This ordering lets a local Visible = Public[T] alias supply Fields[Visible], and
lets a type function return another record template directly. The existing record
materializer still owns the finite visible-TypedDict frontier and family output.
Runtime uses Python's native lexical alias identities and the existing frontend
binding policy, including its ordinary bare-alias fallback; specialization never
replays the construction body.

### Named type captures

Capture constructs an immutable GenericAlias token around a frozen declaration
symbol. Labels are presentation data; declaration identity distinguishes even
equally named tokens. The base implementation requires no optional dependencies.
Runtime lowering gives each token a scoped TypeSymbol. Source capture uses retain
their declaring SourceSpan independently of their use span, and lower into the
same CaptureReference data. Alias substitution preserves those identities.
Module capture declarations remain public values with an `object` annotation in
generated interfaces; they do not leak Typeforge helper annotations. Callable
relationship IR retains the same symbol in CaptureType. Ordinary callable Maps
and finite Each/Collect positions support independent captures. Each position
receives fresh native parameters while retaining capture declaration identities.

EvaluationContext stores immutable named bindings. Matching extends tentative
bindings, reconciles repeated positions through the existing exact type operation,
and discards a failed attempt. Nested Maps reuse existing bindings; generic
parameters keep their original arguments. Output lookup reports an unbound-capture
issue when a needed token was not bound. Raw Input may test an already resolved
binding but does not infer type arguments from values.

Compatible interface captures project list and tuple arguments to Sequence element
positions. TypeSystem.generic_type supplies backend-owned family facts and
normalizes native tuple markers; shared sequence_elements owns the supported
family relation for both fixed compatibility and capture projection. A
heterogeneous tuple contributes an element union. Projection retains the original
semantic values and their unresolved provenance before named matching; it does
not widen bool to int or reconcile repeated captures through a common supertype.
Known subject-union members evaluate complete outputs with their own bindings.
Opaque generic origins fail through the typed semantic seam; other known families
remain ordinary mismatches. This frontier does not promise open generic
inheritance or callable inference.

AlternativeTypePattern represents a union containing structural capture patterns.
Ordinary type unions retain their existing expression/type representation. Matching
retains each successful alternative's condition and immutable bindings; nested
positions continue each environment independently and discard failed attempts.
MapSelection.output_contexts carries those environments to Evaluator, which
instantiates complete outputs before using the existing union builder. Bindings
are never merged across successful alternatives. Branch order remains unchanged;
alternatives within one branch have no priority. An unbound output capture or
adapter failure stops evaluation through the existing typed boundary. Possible
alternatives preserve speculative reachability and conservative output bounds.

An opaque generic parameter cannot reveal structural arguments. Shared evaluation
reports a distinct unresolved-capture issue. Source adaptation retains that typed
reason and, only for a generic type-function declaration, recovers to an `object`
output bound. Concrete applications still evaluate the retained source template;
other failures propagate. Known parameterized shapes preserve available argument
types and their provenance. Callable projection can supply
UnresolvedCaptureBindings when an opaque position needs a possible output bound.
The shared matcher preserves known positions and each alternative's context, then
instantiates complete outputs. Other consumers retain the unresolved-capture
failure; this projection does not infer arguments from runtime values.

## Library and project output

Published library stubs must be deterministic from library source and configuration. Consumer call sites must never influence them, and consumers should not need to run the Typeforge compiler.

Project integrations may use local context to improve precision. These transformations remain in memory, never rewrite authored files, and are not publishable by default.

### Callable input coverage

Relationship IR preserves an omitted Map default as None, separately from an
explicit Never output. Source type parameters retain bounds or constraint domains,
default presence, and authored spans. Adaptation expands selectors and bounds
through the existing alias owner, respecting visible type parameters.

Specialization projects no-default Maps into closed covered input signatures or
bounded generics. Coverage uses the compiler's existing type adapter and local
class ancestry; it does not execute application code. Its containment proof treats
an Any parameter as admitting all known input types, independently of matching a
known Any subject. Possible outputs retain complete alternatives, including
reachable subclass branches. Redundant broad overloads are removed. Bool/int
literal collisions use an aggregate output signature where precise overloads
would fail a supported checker; shared Map literal identity stays unchanged.
Adaptation retains resolved Protocol identity independently of its emitted import
spelling, including parameterized and aliased Protocol bases.

Exact-only class selectors cannot establish a subtype-closed native parameter
domain. Structural TypedDict/Protocol parameters also require matching structural
facts before their coverage can be promised. Unsupported coverage returns
UNREPRESENTABLE_COVERAGE on the authored callable with bound, specialization, or
fallback guidance. Each/Collect uses the same covered native input domain at
finite positions and in its variadic fallback. Explicit defaults retain the
existing output-projection path.

Pipeline exposes type-parameter projections using retained contracts, generated
signatures, and authored spans. Overlay consumes those facts and the public binder
emitter to restrict inputs while preserving original type parameters in the body.
Verification continues to consume the authored relationship. Native mypy, Pyright,
and Pyrefly enforce parameter bounds and check expressions; Typeforge does not
infer ordinary Python values itself.

### Callable output projection

Retained callable IR lowers through the compiler semantic adapter into shared
Map evaluation. Capture tokens retain declaration identity; whole-subject captures
preserve original generic parameters and bounds. Generated capture parameters avoid
authored names, including unused enclosing class parameters. Native overload inputs
remain within authored bounds; an overload covering the bound replaces an
unreachable broader signature.

Native parameter domains include compatible subclasses. Exact selectors and
structural container selectors therefore retain every possible output from those
domains, including reachable fallbacks. Repeated native type variables may infer a
join, while semantic repeated captures still require exact agreement. Complete
alternative outputs remain correlated before union construction.

For opaque structural arguments, compiler-owned capture bindings supply scoped
existential placeholders. Shared matching retains actual known bindings alongside
them. Emission erases only the placeholders: covariant positions use object;
invariant positions use Any. Missing captures remain failures. Callable acceptance
rejects reached or speculative no-match paths whose input coverage cannot be
promised. A nested no-default Map can reuse an original generic bound when the
existing native-domain proof covers that entire bound. An exact selector does not
cover compatible subclasses. Internal template evaluation retains its existing
speculative policy.

Pipeline AnnotationProjection facts expose native input and output annotations
with their authored spans. Body annotations retain original generic names and erase generated parameters
absent from that scope. Native checkers enforce these ordinary bounds; this does
not prove an arbitrary dependent implementation. Native inference for gradual Any
remains checker-owned. Recognized guard verification uses the original
relationship separately from projected native output bounds.

### Each and Collect projection

Each positions reuse scalar callable specialization for coverage, complete output
alternatives, missing captures, and nested no-match failures. Fresh position
parameters preserve authored bounds and constraints, including native constraint
coercion. Name allocation reserves enclosing parameters and previously generated
positions. The configured arity frontier controls finite tuple signatures.

Finite closed branch combinations retain per-position outputs. Crossing partial
generic fallbacks can overlap with incompatible tuple returns in existing
checkers; specialization emits one complete fixed-arity aggregate instead of
claiming those exclusions. Its output retains both reachable transformations and
the fallback. Independent capture parameters and complete alternative unions
remain local to each position.

Beyond the frontier, the same scalar coverage proof supplies the variadic input
domain and a homogeneous possible-output tuple. This preserves omitted-default
input contracts at every arity. Untransformed TypeVarTuple identity still uses
native variadic typing and retains known positions beyond the configured frontier.
Adaptation retains mapped Each/Collect contracts for native body projection;
ordinary unmapped roots retain their existing origin and emission behavior.

## Implementation verification

Implementation verification produces checker-neutral obligations from Typeforge relationships and authored control flow. Existing type checkers validate the expressions; Typeforge does not infer ordinary Python expression types itself.

Precise obligations are emitted only for recognized flow. Unknown predicates, ambiguous controllers, generators, and declaration-only bodies must degrade to an aggregate check or remain with the underlying checker rather than inventing a narrowing.

ReturnContract retains the original Map, authored callable, and compiler-owned
type facts. FlowState records narrowed runtime inputs independently. Whole-type
Is selectors retain reachable fallback obligations after both isinstance and
exact runtime type guards: narrowing a value does not establish the original
generic identity. A whole-union alternative can reach both guard paths; a member
match removes it from the opposite path only when every member matches.

Verification clips alternatives to authored domains through the existing scalar
coverage owner. When clipping changes the subject, shared semantic evaluation
selects its output. The same native-domain proof excludes unreachable compatible
fallbacks, so a valid bare int mapping is accepted while exact int behavior keeps
the bool and original-union counterexamples. Specialization and verification share
stub_type_environment for local ancestry and Protocol identity. Runtime inheritance
facts stay distinct from numeric assignment widening.

The overlay emits these obligations at authored return spans and delegates
expression inference to the native checker. Rebinding a controller invalidates
its flow facts; unknown or disconnected predicates retain aggregate checking.
This finite recognized-flow frontier does not prove arbitrary dependent Python
implementations.

## Compiler plans and target projections

`compiler.source` parses one authored snapshot. Its compiler-internal
`ParsedSource` carries the Python AST alongside `SourceModule`, whose Typeforge-owned
facts include the exact text, declarations, identifiers, and source locations.
Parsed syntax locations use one-based lines and zero-based UTF-8 byte columns;
syntax errors retain Python's character offsets. Projection and integration code
own conversion to editor or checker coordinates.

Source Map slices normalize at parsing into existing marker expressions. Empty
endpoints synthesize the None type anchored to the authored branch; explicit
endpoints retain their own spans. Selector-only literal sugar and inline unary
predicate binding preserve ordinary output roles and structural patterns.
Invalid slice spelling returns SourceSyntaxError with an authored UTF-8 span;
the parser does not execute annotations. Existing marker normalization continues
to own general arity and entry-role validation, and alias binding remains with
the existing frontend expansion owners.

Adaptation interprets annotations, expands aliases, and materializes records. Its
`StubModule.reusable_elements` retains authored callable contracts and reusable
type expressions before declaration rewriting and finite specialization discard
their original form. Origins associate these elements with authored spans and
always refer to elements reachable in the current immutable module snapshot.
Retained roots do not emit additional declarations or imports.

`compiler.verification` analyzes the original bodies against retained typed
contracts. It produces expected and narrowed types with explicit return or
implicit fallthrough sites. It owns flow analysis; it does not choose indentation,
insertion offsets, generated names, or checker document models.

`compiler.pipeline.compile_source` assembles a complete `CompilationPlan` containing
source facts, specialized IR, and verification obligations. The plan exposes no
AST. Failed compiler stages return their modeled failure without publishing a
partial plan; an empty verification result is valid for unsupported flow.

`overlay.project_overlay` consumes that plan to emit declarations and checks,
place edits, and construct source mappings and diagnostic provenance.
`transform_source` preserves its sentinel and invalid-arity fast paths, then
compiles once and projects. Diagnostics use authored descriptions and provenance;
neither consumer reparses source or reconstructs compiler stages.

Adaptation retains inline Map annotation roots alongside Schema roots and authored
callable contracts. Assignment annotations, including local variables, are source
facts collected during parsing. Overlay edits choose the outermost retained root
to avoid overlapping replacements, and convert UTF-8 source columns to character
offsets. Maps project through the existing conservative output fallback, including
nested aliases and overload annotations; Schema retains evaluated selection.
The shared stub-IR traversal handles nested typing constructs. Publication excludes
assignment annotation roots from its source scope and retains its existing surface
and record-field policies.

For published stubs, `generate_module` reads the file once and passes its parsed
snapshot to `compiler.module_surface`. Surface inspection reuses the original AST
to validate and preserve imports and variables. Publication then compiles its
existing selected source scope and emits a complete interface without verification
instrumentation. Syntax failures precede surface failures, which precede compiler
failures. Published relationship aliases retain their conservative `object`
fallback; overlays retain their union-of-outputs fallback.

## Explicit record semantics

`TypedDict`, dataclasses, protocols, ordinary classes, attrs classes, and validation models have different construction, inheritance, and mutation semantics. Typeforge must support each family through an explicit adapter rather than treating every annotated object as the same kind of record.

`Record(expression for field in Fields[T])` constructs an immutable template.
Runtime construction consumes the generator once with a symbolic field. The
template retains its record operand and declaration identity so Python can
discover and substitute type parameters even when every output is Drop. A
construction-scoped context records the operand; it is reset after success or
failure. Specialization neither stores nor replays the generator. The compiler
parses the same supported comprehension without executing authored code.

Both frontends lower to RecordExpression with a scoped field symbol. Evaluation
uses each original RecordField in an immutable child context. Whole-field
passthrough preserves requiredness, readonly state, and backend-owned metadata;
Drop removes the entry. Keyword Field construction requires name and type and
defaults to required, writable output. FieldReplacementExpression changes only
supplied values using the original immutable RecordField. An omitted override is
distinct from an explicit None type or false flag. Replacing the type replaces its
complete Annotated value; wrapping field.type keeps its metadata at the nested
position. Replacement type Drop removes the entry; other field positions require
a valid name, type, or boolean. Output names must be Python identifiers.
Known union field types retain their member structure for matching. Only the
replacement type position enables Map's field-replacement output role: a concrete
Drop consumes the whole entry after every selected member and capture alternative
has evaluated successfully. Ordinary unions and nested type arguments remain
type-only. A speculative Drop returns a typed unsupported-layout failure rather
than becoming a definite removal.
Runtime templates transport string names as Literals so typing reconstruction
preserves names rather than resolving them as forward references.
Record construction clears its operand's whole-record metadata; explicit outer
Annotated supplies metadata for the new result.
Duplicate names and outputs other than a field or Drop are typed failures.
Ambient Key/Value and MapFields authoring are removed.

Known record-union operands transform each TypedDict alternative independently.
Shared RecordUnion data retains complete output shapes; corresponding fields are
never merged into unrelated unions. Field contexts change for each alternative,
while generic arguments and enclosing capture bindings keep their original
values. Reflection or transformation failure in any alternative fails the whole
application. Never cannot turn into an empty record. Composition consumes complete
record alternatives, and construction clears both member and whole-union metadata.
Explicit outer Annotated applies metadata to the resulting union once.
Runtime emission uses Pydantic's native union schemas; concrete compiler
applications emit unions of generated TypedDict declarations.

TypedDict reflection, compiler discovery, and synthesized output remain with the
existing family adapters. RecordShape retains its family identity rather than
treating annotated objects uniformly, leaving future Protocol output a separate
adapter decision. Compiler materialization currently specializes named aliases
with one type parameter over visible TypedDict declarations; runtime Schema also
supports concrete inline records and Pydantic generic model specialization.

Shared `AnnotatedExpression` carries backend-owned metadata around a type or a
synthesized record. Evaluation preserves record metadata in order without
interpreting it; type annotations use the backend's ordinary type construction.
This lets a Map select an annotated record while keeping annotation execution and
schema construction in the consumer.

## Pydantic runtime integration

The public `typeforge.pydantic.Schema` annotation adapts Python typing objects,
evaluates shared expressions, and emits Pydantic schemas. Its stateless hook
recompiles the current source supplied by Pydantic, including generic
specializations and rebuilds. There is no separate runtime expression evaluator.

The frontend owns marker recognition and alias binding; the runtime TypeSystem
owns primitive type operations, with TypedDict reflection in the record adapter.
Runtime matching uses a TypeSystem configured with the frontend's selection-type
resolver. Reflected aliases reuse ordinary alias binding and cycle detection when
their type facts are needed. Original field annotations remain available for
passthrough and Pydantic metadata; Annotated unions expose effective member types
while retaining their member annotations.
Policy owns generic fallback and Input test admissibility from adapted facts.
Outcome translation preserves authored expressions and distinguishes no-match
from explicit Never and unsupported record operands. Resolved and deferred
emission own CoreSchema construction; raw observation owns Python value matching.
The inert Input marker is independent of compilation, keeping imports acyclic.

Pydantic owns model lifecycle, leaf validation, metadata, and serialization.
Schema-time transformations add no Typeforge validation callbacks. Deferred
Maps consume shared selection results before validating one output and retain
field/capture bindings without inferring static generic arguments from values.
Serialization can distinguish output types but does not retain branch history
for indistinguishable values. Neither compiler implementation imports the runtime
integration nor the runtime integration imports the compiler.

Importing base Typeforge does not load Pydantic. The optional integration guard
reports missing Pydantic dependencies specifically and propagates unrelated import
failures. A future compiler plugin may reuse policy inside the integration;
plugin loading and static integration diagnostics remain separate work.

## Result boundaries

Use `typeforge.utils.error_handling.safe_result` at a seam whose implementation
consumes nested `Result` values. Declare the accepted error types and call
`.unwrap()` where a nested failure should stop the operation:

```python
@safe_result(errors=(RenderError,))
def render_document(document: Document) -> str:
    header = render_header(document).unwrap()
    body = render_body(document).unwrap()
    return header + body
```

The decorated function returns `Result[str, RenderError]`. Private helpers inside
the boundary return plain values. The utility uses `returns.safe` to catch the
declared exception types and `UnwrapFailedError`, then recovers the original
declared failure from its `Failure` container. This also supports error dataclasses
that are not exceptions. It preserves error identity and short-circuits later
steps; unexpected exceptions, undeclared failures, and unwraps of other container
kinds propagate. There is no default catch-all error type.

For several unrelated error classes, annotate the tuple with the intended union
so both mypy and pyright retain that precise failure type:

```python
_RENDER_ERRORS: tuple[type[ParseError | RenderError], ...] = (ParseError, RenderError)
```

Pass that tuple as `safe_result(errors=_RENDER_ERRORS)`.

When the seam translates another module's error into its own model, wrap the
implementation once and map the resulting failure at that boundary:

```python
def project(plan: Plan) -> Result[Document, ProjectionError]:
    project_safely = safe_result(errors=(RenderError,))(_project)
    return project_safely(plan).alt(
        lambda error: ProjectionError(plan.path, error.message)
    )
```

Use explicit failure branches for decisions such as recovery, fallback, or
skipping an unsupported obligation. These decisions differ from propagation and
must remain visible. Existing exception-based callers may use `ok()` to re-raise
an exception-only result; `returns.safe` remains sufficient for seams that only
catch directly raised domain exceptions. The shared utility depends on no
Typeforge domain or target modules; callers supply their own error classes.
