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
Static type emission is shared with record materialization; schema origins follow
normalization without merging independent boundary roots. Production declaration
adaptation and reusable Schema roots both use this adapter. Callable Map
relationships retain their overload path; record aliases retain their existing
materialization stage, and Each/Collect retain finite specialization.

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
