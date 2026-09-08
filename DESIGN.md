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
Legacy branches remain for repository migration and are removed at the authoring
cutover tracked in `docs/in_progress_tasks/map-slice-syntax.md`.

`Map` is Typeforge's central input/output type machine. Its ordered `Case`
branches accept either exact or structural type patterns or boolean predicates;
the first matching pattern or true predicate selects the output. `Default`
handles the unmatched path and omission means `Never`.

Pattern and predicate cases share one ordering model. Structural patterns may
capture `Value`, while predicates may compose `Equal`, `Assignable`, `All`,
`Any`, and `Not` and may inspect contextual `Key` and `Value` bindings inside
`MapFields`.

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
concrete. Policy decides explicitly whether to reject such a path. Pydantic
accepts speculative no-match bounds and rejects reached no-match paths; unrelated
semantic errors still propagate. The existing `evaluate(expression, type_system)`
entry point remains the default-policy convenience used by compiler consumers:
exhausted selections produce Never and its failure type remains SemanticIssue.

Compiler semantic lowering keeps field-name expressions distinct from typing
types and output templates. A string Literal can name a transformed field while
remaining an ordinary typing Literal in that field's type. Output-template roles
compose through unions and parameterized arguments, preserving contextual Value
bindings. Production Schema boundaries evaluate through shared semantics,
including deferred Input bounds and unresolved static type identity.

The compiler's source schema adapter expands authored aliases before shared
lowering, keeping callable relationship IR separate. It requires the source
snapshot's alias context and preserves omitted defaults and authored cycles.
The same expansion owner resolves predicate aliases for callable adaptation and
record materialization while preserving ordinary type aliases on those paths.
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

The runtime frontend carries an explicit selector subject through predicate
aliases, compound conditions, and Annotated wrappers. Nested Maps establish a
new subject; output types and explicit predicate operands receive no implicit
subject. Alias type parameters retain their existing identity-based bindings.
Literal normalization is shared with construction. Neither frontend stores
implicit predicates in shared semantic data or changes union matching policies.

Pydantic diagnostic display reconstructs slice branches from canonical typing
arguments without expanding aliases or interpreting Literal/Annotated payloads.
Issue data, codes, phases, and validation locations stay unchanged; display does
not add authored-state storage to the runtime constructor or semantic evaluator.

## Library and project output

Published library stubs must be deterministic from library source and configuration. Consumer call sites must never influence them, and consumers should not need to run the Typeforge compiler.

Project integrations may use local context to improve precision. These transformations remain in memory, never rewrite authored files, and are not publishable by default.

## Implementation verification

Implementation verification produces checker-neutral obligations from Typeforge relationships and authored control flow. Existing type checkers validate the expressions; Typeforge does not infer ordinary Python expression types itself.

Precise obligations are emitted only for recognized flow. Unknown predicates, ambiguous controllers, generators, and declaration-only bodies must degrade to an aggregate check or remain with the underlying checker rather than inventing a narrowing.

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

Shared `AnnotatedExpression` carries backend-owned metadata around a type or a
synthesized record. Evaluation preserves record metadata in order without
interpreting it; type annotations use the backend's ordinary type construction.
This lets a Map select an annotated record while keeping annotation execution and
schema construction in the consumer. Field operators continue to define output
requiredness and readonly flags explicitly.

## Pydantic runtime integration

The public `typeforge.pydantic.Schema` annotation adapts Python typing objects,
evaluates shared expressions, and emits Pydantic schemas. Its stateless hook
recompiles the current source supplied by Pydantic, including generic
specializations and rebuilds. There is no separate runtime expression evaluator.

The frontend owns marker recognition and alias binding; the runtime TypeSystem
owns primitive type operations, with TypedDict reflection in the record adapter.
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
