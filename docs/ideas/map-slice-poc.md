# Slice Map feasibility POC

This is a throwaway experiment on `neil/map-slice-poc`, not a completed public
syntax migration. It answers whether this spelling can use Typeforge's current
compiler and runtime models:

```python
type Encoded[T] = Map[
    T,
    int: str,
    Assignable[bytes]: str,
    ...: T,
]
```

**Verdict: yes, with two normalization points and some integration work.** The POC
does not change any source-domain, stub-IR, semantic-expression, or evaluator data
structures. It also leaves the Pydantic frontend, schema emission, and validation
implementation unchanged. AST parsing alone is insufficient for runtime use,
inline checker overlays, and reusable unary predicate aliases.

## Run it

```sh
uv run python scripts/slice_map_poc.py
uv run pytest -q tests/unit/compiler/source/test_slice_map_prototype.py tests/unit/pydantic/test_slice_map_runtime_prototype.py
```

The demo prints raw and normalized generic substitutions, the parsed source
model, generated stubs, specialized Pydantic model outputs, structural capture,
and deferred Input dispatch. The tests include successful behavior and explicit
characterizations of unresolved limitations; a passing test count does not mean
all proposed authoring forms work.

Environment: Python 3.14.3, Pydantic 2.13.4, mypy 2.2.0, Pyright 1.1.411,
Pyrefly 1.1.1, and Ruff 0.15.21. No dependency or lockfile changes.

Verification completed: all 58 POC cases pass, including the expected-failure
characterizations. Focused checks and full `make check` pass: pytest, Ruff lint
and formatting, Flake8 block spacing, mypy, and Pyright.

## What the prototype changes

The source parser recognizes `ast.Slice` entries directly inside a recognized
Typeforge `Map` subscription. It constructs existing `MarkerTypeExpression`
values for `Case` and `Default`, preserving the authored branch text and spans.
Inline unary `Assignable[X]` and `Equal[X]` receive the enclosing Map's subject;
`All`, `Any`, and `Not` recursively bind their predicate operands. Nested Maps
normalize independently, so their selectors use their own subjects.

Bare string, bytes, boolean, and integer selectors become existing `Literal`
applications. Exact and structural selectors remain the existing case patterns;
they are not indiscriminately converted to boolean `Equal` expressions, which
would lose structural captures.

The separate `typeforge._slice_map_prototype.Map` construction facade converts
runtime `slice` objects into existing `Case`/`Default` generic aliases. It returns
a generic alias whose origin is the existing canonical public `Map`. This happens
when annotations are constructed/evaluated, not on application validation paths.
It performs no user callback execution, type matching, or validation itself.

The normal public `from typeforge import Map` runtime export is unchanged.
Production adoption needs an explicit separation between the authoring constructor
and the canonical marker identity recognized by frontends. Simply replacing the
export with a class would change identity checks and the ordinary `object`
fallback. The separate facade demonstrates feasibility without choosing that
public declaration design prematurely.

## Evidence

| Path or behavior | Result |
| --- | --- |
| Python parsing and runtime subscription | Slice syntax is valid Python. |
| Static callable generation | Simple types, literal selectors, unary predicates, compound predicates, missing defaults, and explicit Never produce the same stubs as their existing spelling. |
| Published `.pyi` consumers | mypy, Pyright, and Pyrefly accept generated interfaces, infer the concrete mapped output, and reject an intentionally wrong `assert_type`. |
| Named-alias overlays | All three checkers accept the transformed source and reject an intentionally wrong implementation return. |
| Inline callable overlays | All three reject the retained slice annotation. This is an unresolved projection requirement. |
| Static Schema evaluation | Concrete types, assignability, literals, structural captures, and nested Maps produce the same emitted types. |
| Record materialization | Field dropping, renaming, optional output fields, and contextual Key/Value bindings work through existing MapFields. |
| Pydantic frontend | Slice and canonical forms adapt to equal semantic expressions and produce equal JSON schemas for the comparison cases. |
| Runtime generics | Named aliases, inline generic model fields, output-only type parameters, independent specializations, and forced model rebuilds work after eager normalization. |
| Runtime selection | Exact versus assignable matching, compounds, bool-versus-int literals, structural capture, nested subject binding, and annotations work. |
| Deferred Input | Selection precedes coercion; failed selected validation does not retry. Unsupported parameterized input patterns retain their existing rejection. |
| Failures | No match, explicit Never, invalid default order, duplicate defaults, missing endpoints, and slice steps are exercised. |
| Compiler isolation | Generation succeeds on authored source containing a top-level division-by-zero tripwire; the compiler does not execute it. |

## Issues that matter for implementation

### 1. Python does not substitute inside raw slices

With the existing marker:

```python
T = TypeVar("T")
expression = Map[T, int: list[T], ...: T]
expression[int]
# Map[int, slice(int, list[T], None), slice(Ellipsis, T, None)]
```

The subject changes, but the branch output parameters do not. A parameter that
appears only inside a slice is absent from `__parameters__` entirely.

Normalizing in the annotation constructor fixes both problems:

```python
# Prototype Map[T, int: list[T], ...: T] immediately becomes:
Map[T, Case[int, list[T]], Default[T]]
# Ordinary specialization now produces:
Map[int, Case[int, list[int]], Default[int]]
```

Waiting until Pydantic's schema hook is too late to rely on ordinary generic
substitution. Named aliases can retain their own explicit parameters, but that
does not solve direct generic model fields or output-only parameters.

### 2. Valid Python is not necessarily a valid checker annotation

Existing overlays add overloads but preserve the implementation's inline return
annotation. mypy reports an invalid annotation, Pyright reports an unexpected
slice instead of a class, and Pyrefly reports a non-type slice.

Alias-based overlays work because Typeforge already replaces their definitions
with ordinary output types. Published stubs also work because all slice syntax
is removed during emission. Production overlays need to project inline Map
annotations to ordinary checker types too, while retaining authored spans and
the original relationship for implementation verification. Existing retained
callable contracts and fallback emission provide relevant machinery; this POC
does not implement that projection change or establish coverage of all nesting
positions.

### 3. Reusable unary predicate aliases need later binding

```python
type Numeric = Assignable[int]
type Selected[T] = Map[T, Numeric: str, ...: bytes]
```

The inline equivalent works; this alias form fails in both frontends. At the
AST normalization point, the selector is a name, and the existing alias pipeline
validates `Assignable[int]` as an incomplete binary predicate. The runtime facade
also sees the alias before its body has been expanded.

If reusable predicate aliases are in scope, normalization must cooperate with
existing alias expansion before predicate arity validation. That can still end
in the same binary predicate data, but cannot be implemented solely as a local
slice-to-Case parser rewrite. Lexical subject binding across aliased and nested
predicates needs an explicit contract.

### 4. None and omitted endpoints are indistinguishable at runtime

`int:None` and `int:` both become `slice(int, None, None)`. Likewise, `None:str`
and `:str` become the same object. The AST knows the distinction; the runtime
constructor does not.

The POC rejects these endpoints and demonstrates `types.NoneType` at runtime.
An alternative language rule could accept both explicit and omitted endpoints
as None. That is a syntax decision, not a semantic-model limitation. Explicit
third-endpoint `None` is also indistinguishable from no step at runtime; exact
malformed-syntax diagnostic parity is not established by this prototype.

### 5. Bare string selectors interact with existing tooling

Ruff's F821 treats strings inside type aliases as forward references, including
slice selectors such as `"password": Drop`. The executable example needs local
F821 suppressions. `Literal["password"]` avoids this issue. Ruff accepts and
formats slices, but uses slice spacing conventions rather than mapping spacing.

Adoption needs a tooling decision: retain explicit Literal spelling where needed,
document scoped lint configuration, or pursue tool support for the new syntax.
Changing Typeforge's semantic representation cannot fix how a separate linter
interprets authored source.

### Existing limitations exposed, not caused, by the syntax

An unbounded callable relationship that captures `list[Value]` and emits
`tuple[Value, ...]` fails stub emission with `unlowered type expression:
MapValueType` in both old and slice spelling. Concrete Schema structural capture
works in both. This needs separate callable-lowering work if that unbounded
form is part of the intended public promise.

The old static source normalizer also accepts a Case after Default whereas the
runtime frontend rejects it. The POC rejects trailing slice branches in the source
parser. A production cutover should define ordering validation once per frontend
with the same contract. Current diagnostic text still mentions Case/Default;
authored text and locations are retained, but the wording needs a syntax update.

## Suggested implementation scope

1. Preserve the current evaluator, case ordering, capture semantics, and IRs.
2. Introduce a production annotation-construction normalizer with deliberate
   canonical marker identity and static fallback behavior.
3. Normalize static slices to existing source expressions; coordinate unary
   predicate binding with alias expansion if reusable predicates are supported.
4. Extend overlay annotation projection so raw slices never reach the checker
   as type arguments, including nested supported positions.
5. Decide None-endpoint and bare-string rules; update diagnostic wording and
   documentation around the resulting syntax.

This POC makes no changes to field-edit syntax, supported record families,
finite-specialization guarantees, evaluator policies, or published fallback
semantics.
