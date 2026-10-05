# Typeforge

Typeforge lets Python developers write type relationships that Python cannot express out of the box. It compiles those relationships into standard typing constructs understood by existing type checkers.

## Why

Python can preserve a generic type, but it struggles to transform one.

A variadic function can retain its input types, but cannot easily transform each one or extract a type from a wrapper:

```python
rows = database.select(
    User.id,       # Column[int]
    User.email,    # Column[str]
    Profile.bio,   # Column[str | None]
)
# Wanted: list[tuple[int, str, str | None]]
# Typical annotation: list[tuple[object, ...]]
```

Input-dependent return types require an overload for every case. For small use-cases this is fine. But it can very quickly add a lot of unnecessary boilerplate to your code.

```python
@overload
def serialize(value: int) -> float: ...

@overload
def serialize(value: bytes) -> str: ...

@overload
def serialize[T](value: T) -> T: ...
```

With Python's current typing constraints boilerplate grows with every type, field, and supported argument count. Typeforge provides a small DSL to dynamically generate this boilerplate (behind the scenes) instead.

Libraries can publish Typeforge-generated .pyi files, giving consumers more precise types without requiring them to install or configure Typeforge. Library authors describe each type relationship once instead of maintaining large @overload blocks, while consumers get accurate inference for each concrete call without needing to understand the generated machinery.

Typeforge isn't a typechecker. That isn't what I wanted to build. `mypy`, `pyrefly`, `ty`, etc. are all doing a great job in that space already. Instead Typeforge works with your existing typechecker. That way you don't need to worry about migrating off your existing technology.

## How it works

Typeforge markers are inert at runtime. The compiler parses source without importing or executing it, then lowers enriched annotations into standard `.pyi` declarations or an in-memory source overlay.

```text
Python source
    -> Typeforge compiler
    -> standard typing constructs
    -> mypy or Pyrefly
```

`typeforge generate` writes complete `.pyi` interfaces. `typeforge check` and the language-server proxy keep transformed source in memory, map results back to the authored file, and never rewrite application code.

For local `Map` implementations, Typeforge also verifies return expressions after recognizable `type`, `isinstance`, literal, `None`, boolean, and `match` guards. It emits ordinary typed assignments in memory and lets the configured checker infer the expression type. Unrecognized flow falls back to the safe aggregate return type.

### Semantic integration seam

`typeforge.semantics` is the supported interface for integrations that adapt
backend-specific types into Typeforge's shared evaluator. It exposes immutable
semantic expressions, family-aware record shapes, the `TypeSystem` adapter
protocol, typed `SemanticIssue` failures, and `evaluate`.

Compiler Schema evaluation and the Pydantic integration use this shared evaluator.
Callable Map specialization remains a separate compiler path. Application code
should use Typeforge markers and `Schema[...]`; the semantic interface is for
integration authors.

## Examples

Capture every argument type and collect them into a heterogeneous tuple:

```python
from typeforge import Collect, Each


def collect[T](*values: Each[T]) -> tuple[*Collect[T]]:
    return values


result = collect(1, "two", True)
# tuple[int, str, bool]
```

Map input types to output types:

Slice construction and compiler source normalization are available through the
public `Map` import:

```python
from typing import TypeVar
from typeforge import Map

T = TypeVar("T")
expression = Map[int, int: list[T], ...: bytes]
specialized = expression[str]
```

The constructor preserves parameters inside selectors and outputs before Python
performs substitution. `None` and empty colon endpoints both denote the None
type; use `Literal["text"]` for string selectors. A fallback must be last, and
non-None slice steps are invalid. Construction does not evaluate relationships;
`Schema[specialized]` uses the existing Pydantic integration.

The compiler normalizes these branches into its existing Case/Default data,
preserving authored locations. Qualified and renamed imports work. Invalid steps,
branches following a fallback, and bare string selectors receive located errors.

Diagnostics describe branches as `selector: output` and fallbacks as `...: output`.
Runtime errors retain their codes and field locations while displaying normalized
Map data in slice notation. Ruff can compact spacing around colons without changing
the expression. The supported examples pass the existing lint rules; raw slices
still require Typeforge projection before ordinary type checking. See the
[tested tooling and diagnostic behavior](CONTEXT.md#tooling-and-diagnostics).

Bare selectors use Python assignment compatibility. `bool` matches `int`,
subclasses match their bases, and `int` matches `float` under Python's numeric
widening rules. `Any` is compatible in either direction. Use `Is[Type]` when the
complete subject must equal a type exactly:

```python
from typeforge import Is, Map
from typeforge.pydantic import Schema

class Payload:
    compatible: Schema[Map[bool, int: str, ...: bytes]]  # str
    exact: Schema[Map[bool, Is[int]: str, ...: bytes]]  # bytes
```

`Is` takes one type argument and binds to its consuming Map. The compiler obtains
local inheritance facts from declarations without importing application code.
The former public predicate helpers (`Equal`, `Assignable`, `All`, `Any`, and
`Not`) have been removed.

For known union subjects, bare branches select each member in order. `Is` tests
the complete original subject, comparing unions without regard to member order:

```python
class UnionPayload:
    distributed: Schema[Map[int | str, int: bytes, str: float]]  # bytes | float
    exact: Schema[Map[int | str, Is[str | int]: bytes, ...: float]]  # bytes
```

A known member without a matching branch or fallback fails the whole Map.
For example, `Schema[Map[int | str, int: bytes]]` fails compilation and runtime
schema construction, including when nested in an outer union. Selecting an
explicit `Never` remains distinct and uses ordinary Python union simplification.

Ordinary aliases expand for selection in both compiler and runtime. Explicit
members beside `Any` are preserved for later exact comparison:

```python
from typing import Any

type Numbers = int | str
type Mixed = Any | str

class AliasPayload:
    value: Schema[Map[Numbers, int: bytes, ...: float]]  # bytes | float
    exact: Schema[Map[Mixed, Is[str | Any]: bytes, ...: float]]  # bytes
```

Selected output aliases retain Pydantic's constraints and schema references.
Recursive aliases needed for Typeforge selection report an alias-cycle failure.

Fully specified generic selectors follow the supported Python variance rules:

```python
from collections.abc import Sequence

class GenericPayload:
    mutable: Schema[Map[list[bool], list[int]: str, ...: bytes]]  # bytes
    covariant: Schema[Map[Sequence[bool], Sequence[int]: str, ...: bytes]]  # str
```

The current frontier includes list, set, dict, frozenset, tuple, Sequence, and
Mapping. Lists and tuples can match Sequence; dict can match Mapping. Mutable
containers use invariant arguments; immutable containers use covariance;
Mapping keeps invariant keys and covariant values. Any retains Python's gradual
compatibility. Unknown generic variance produces a diagnostic instead of selecting
a fallback. Identical opaque generic types can still match. Compatible interface
captures and full reasoning over unresolved parameters remain subsequent slices.

Typeforge overlays project inline Maps in parameters, returns, fields, variable
annotations, and nested alias values to ordinary checker types. Generated overloads
retain mapped call results; authored contracts still drive implementation checks.
Inline annotations use the conservative union of branch outputs and the fallback,
whereas `Schema[Map[...]]` uses evaluated selection. Projection preserves authored
files and diagnostic locations. Raw slices require Typeforge processing before
ordinary type checking.

Published stubs support slice-authored callable relationships and finite
`Each`/`Collect` specialization. Consumers use ordinary mypy, Pyright, or Pyrefly without
running Typeforge. For example, `Map[T, int: str | None, ...: bytes]` gives an
integer call `str | None`; calls outside that overload retain `str | None | bytes`.
Relationship aliases themselves publish as `object`. Named captures resolve through
type-function and Schema templates and retain existing finite Each/Collect
specialization with one capture per structural branch. Broader callable capture
precision is a later slice.

Callable overloads follow checker subtype matching, so exact selectors cannot
exclude subtypes such as `bool` from `int`. Callable union selectors and selection
involving `Any` do not yet have a portable cross-consumer guarantee.
See the [callable support limits](CONTEXT.md#callable-support)
before relying on these forms to reproduce `Schema` selection.

Slice branches are the public authoring syntax. `Case` and `Default` are no
longer exported. Internal branch data remains unchanged.
See the [authoring contract](CONTEXT.md#map-authoring)
and [union limitations](CONTEXT.md#union-support-and-agreed-future-contracts).

```python
from typeforge import Map


def serialize[T](value: T) -> Map[
    T,
    int : float,
    str : bytes,
    ... : T,
]:
    ...

result_1 = serialize(5) # float
result_2 = serialize("test") # bytes
result_3 = serialize([123]) # float | bytes | list[int]
```

Each selector is a compatible type pattern or an exact `Is[Type]` selector.
Branches share one declaration order, and the first matching branch wins.

Choose a return type from a boolean flag:

```python
from typing import Literal

from typeforge import Map


type FetchResult[T: bool] = Map[
    T,
    Literal[True] : dict[str, object],
    ... : bytes,
]

def fetch[T: bool](
    url: str,
    *,
    parse_json: T,
) -> FetchResult[T]:
    ...


data = fetch("/users", parse_json=True)   # dict[str, object]
raw = fetch("/users", parse_json=False)   # dict[str, object] | bytes
```

Capture and reuse the inner type of a generic wrapper:

```python
from typeforge import Capture, Map, type_function


class Option[T]:
    value: T


@type_function
def QueryResult[T]():
    Item = Capture("Item")
    return Map[T, Option[Item]: Item | None, ...: T]


type Result = QueryResult[Option[int]]  # compiler output: int | None
```

Concrete template specializations retain their captured arguments. Callable
structural capture publication remains a later slice.

Map a `TypedDict` and attach Markdown documentation to the resulting type:

```python
from typing import Annotated, TypedDict

from typeforge import Doc, Key, MapFields, OptionalField, Value


class User(TypedDict):
    name: str
    age: int


type Patch[T] = Annotated[
    MapFields[T, OptionalField[Key, Value]],
    Doc("Fields that should be updated."),
]


def update_user(changes: Patch[User]) -> None:
    ...

# `changes` has optional `name: str` and `age: int` fields.
# Hovering over `Patch` shows its documentation.
```

## Reusable type functions

A type function gives a type definition its own scope and returns a reusable
template. Runtime construction happens once during import; subscription and value
validation specialize that template without running the body again.

```python
from typeforge import Map, type_function
from typeforge.pydantic import Schema
from pydantic import TypeAdapter

@type_function
def Selected[T]():
    return Map[T, int: str, ...: bytes]

TypeAdapter(Schema[Selected[int]]).validate_python("hello")  # "hello"

@type_function
def Items[T]():
    return list[Selected[T]]

type TextItems = Items[int]  # compiler output: list[str]
```

Compilation and source files are optional for runtime use. The compiler reads the
supported construction syntax without importing or executing the application and
emits ordinary typing aliases and specialized annotations for existing checkers.
An unresolved Selected[T] has the output bound str | bytes.

The basic compiler scope supports a module-level synchronous function with no
value parameters or other decorators, unconstrained ordinary type parameters
without defaults, an optional docstring, and one final return of a type expression.
Map, Is, unions, ordinary generic types, and subscription of other type functions
work. Capture declarations may precede the return. Local aliases and Record/Fields
arrive in later slices.

Runtime construction can use additional Python statements when they produce a
valid template. It rejects invalid returned structures and foreign unbound
parameters; symbolic parameter and Map truthiness is invalid. Use Map for
selection that depends on unresolved types. Runtime acceptance of additional
construction code does not establish compiler support.

### Named captures

Capture tokens give discovered types explicit names. Their labels help diagnostics;
two declarations with the same label still identify different tokens.

```python
from typeforge import Capture, Map, type_function

@type_function
def SamePair[T]():
    Item = Capture("Item")
    return Map[T, tuple[Item, Item]: Item, ...: bytes]

type Same = SamePair[tuple[int, int]]  # compiler output: int
type Mixed = SamePair[tuple[int, str]]  # compiler output: bytes
```

Repeated positions require exact type agreement, including union set equivalence.
Failed branches discard tentative bindings. A nested Map reuses an already bound
token; declaring another token creates an independent binding. Enclosing generic
parameters retain their original supplied arguments. Reading an unbound capture
reports an error rather than selecting a fallback.

The compiler supports literal Capture declarations at module scope and in type
functions. Declaration variables must be unique within each scope. Capture tokens
are immutable and do not become caller-supplied type parameters. An unconstrained
generic subject reveals no container arguments, so its unspecialized type-function
declaration currently projects the safe `object` bound. Concrete applications and
already known generic shapes remain precise. Alternative capture patterns arrive
in a subsequent slice.
Structural `Value` authoring has been removed; `Value` remains a MapFields field
reference until the Record/Fields cutover.

`Sequence[Item]` also captures elements from lists and tuples:

```python
from collections.abc import Sequence

@type_function
def Element[T]():
    Item = Capture("Item")
    return Map[T, Sequence[Item]: Item, ...: bytes]

type Flag = Element[list[bool]]  # bool
type MixedElements = Element[tuple[int, str]]  # int | str
type Text = Element[tuple[str, ...]]  # str
```

These captures preserve the actual element types. A heterogeneous tuple contributes
the union of its elements; separate subject-union members keep their own bindings
through complete outputs. Repeated captures still require exact agreement.
Compatible interface captures currently support list, tuple, and Sequence origins.
Unknown generic origins produce a diagnostic instead of choosing a fallback;
other known families, such as set, do not match Sequence.

## Pydantic integration

Install the optional Pydantic extra, then wrap a Typeforge expression in
`Schema[...]`:

```console
pip install "typeforge[pydantic]"
```

```python
from typing import Literal, TypedDict

from pydantic import BaseModel
from typeforge import Drop, Field, Key, Map, MapFields, Value
from typeforge.pydantic import Schema


class User(TypedDict):
    name: str
    password: str


type Public[T] = MapFields[
    T,
    Map[
        Key,
        Literal["password"] : Drop,
        ... : Field[Key, Value],
    ],
]


class Response(BaseModel):
    user: Schema[Public[User]]
```

Pydantic compiles this to a native typed-dictionary core schema, and validation
returns an ordinary `dict`; `Schema` is not a value wrapper. Schema-time `Map`
expressions add no Typeforge Python calls during validation. Expressions
using `typeforge.pydantic.Input` intentionally dispatch on each raw input value
before letting the selected Pydantic schema validate it.

Slice Maps also compose inside `MapFields`, using `Key` for field names and
`Value` for field types. Explicit field operators replace the source modifiers:
`Field` makes a field required and writable, `OptionalField` makes it optional
and writable, and `ReadonlyField` makes it required and readonly. Pydantic retains
field constraints and record metadata; generated TypedDicts use the compiler's
existing base-type projection for Annotated fields. Nested Maps over union-valued
fields still differ between compiler materialization and runtime evaluation;
see the [field support limits](CONTEXT.md#field-support).

### Generic model fields

`Schema` works on ordinary generic `BaseModel` fields, including nested containers
and aliased Typeforge expressions. Pydantic owns specialization, inheritance,
field configuration, validators, serializers, and `model_rebuild()`:

```python
from pydantic import BaseModel
from typeforge import Map
from typeforge.pydantic import Schema


class Payload[T](BaseModel):
    value: Schema[Map[T, int: str, bytes: int]]


assert Payload[int](value="3").value == "3"
assert Payload[bytes](value="3").value == 3
```

Unparametrized fields follow Pydantic's fallback order: a type default, constraints,
a bound, then `typing.Any`. Typeforge applies transformations to that fallback
while preserving Pydantic's validation and serialization behavior for TypeVars.
It never infers an omitted model type argument from submitted values.

For a static Map, `Any` uses gradual compatibility for fixed selectors, including
`int`, but reveals no arguments for `list[Item]`. A known `list[Any]` can bind
an Item capture to `Any`.
Unmatched cases proceed to the authored default. With no default, direct concrete
schema construction raises `PydanticSchemaGenerationError` with `[map_no_match]`.
A generic model can still be defined and specialized: validating an unmatched
fallback, such as `Payload(value="3")` above, raises a field-located
`ValidationError` with code `typeforge_map_no_match`. Its JSON Schema describes
the uninhabited field with `{"not": {}}`.

An explicitly selected `Never` output also rejects schema construction, with
`[expected_type]`; it is distinct from a Map that found no matching case.

### Raw Input dispatch

```python
from pydantic import TypeAdapter
from typeforge import Map
from typeforge.pydantic import Input, Schema


adapter = TypeAdapter(Schema[Map[Input, str: int, ...: float]])
assert adapter.validate_python("3") == 3
assert type(adapter.validate_python(3)) is float
```

Input dispatch selects the first matching case before output coercion. For
example, `"bad"` selects the `int` output above and fails integer validation;
validation does not retry another case or the default. Nested Maps see the same
raw value until output validation begins, while Input inside a container's item
schema observes each item.

Supported raw Input tests include Python types, unions, `Annotated` wrappers,
`Literal` values, `Input` as a catch-all, and exact `Is` selectors. Raw Input
type tests currently distinguish `bool` from `int`. Literals compare both type
and value:
`Literal[1]` does not match `True`, `1.0`, or an integer enum member. Annotation
validators are not executed to choose a case.

`None` and empty slice endpoints both mean the None type: `Map[Input, :,
...: str]` accepts None or a string. Ordinary type aliases expand for static and
raw Input selection; raw tests observe their leaf types.
Selected output aliases keep Pydantic's constraints and schema references.
Raw Input type observation and static compatibility remain distinct. Union
construction preserves explicit members beside `typing.Any`. The
[union support boundary](CONTEXT.md#union-support-and-agreed-future-contracts)
records the supported cases and remaining cross-consumer restrictions.

Parameterized value-time patterns such as `list[int]` and `list[Item]` fail
construction with `[unsupported_runtime_pattern]`, including under unions,
annotations, and aliases. Runtime dispatch does not capture types from container
values. Existing static captures and MapFields bindings remain available.

No matching Input case or default produces `typeforge_map_no_match` during
validation. A reached predicate failure retains its `typeforge_` diagnostic code,
such as `typeforge_unbound_key`; it is never treated as a mismatch. Short-circuited
operands remain unvisited. Errors retain authored field/item locations and input
values. Malformed markers fail during parsing, and unexpected hook or validator
exceptions propagate.

Returned values have no dispatch wrapper. Serialization observes output types
and delegates their Pydantic serializers. When different branches produce
indistinguishable outputs with different serializers, the original branch cannot
be recovered; branch-history serialization is not guaranteed. Deferred Input JSON
Schema is currently `{}` in both validation and serialization modes.

### Records and supported expressions

MapFields supports `TypedDict` records, including inherited and generic fields,
renaming, Drop, metadata, and readonly information. Field operators explicitly
set output requiredness and readonly state: `Field` is required, `OptionalField`
is optional, and `ReadonlyField` is required and readonly. An invalid concrete
record operand fails construction; an invalid unparametrized fallback reports
`typeforge_unsupported_record` at validation while allowing valid specialization.

Ordinary model output types delegate to Pydantic. Transforming BaseModel records
or structurally capturing their generic arguments is outside this integration's
supported scope. Ordinary recursive aliases delegate to Pydantic; recursive
aliases containing Typeforge operators fail explicitly. Variadic Typeforge aliases
require specialization or a finite default. Callable-only `Each` and `Collect`
relationships have no Pydantic model-field semantics.

### Compiler output

For generated typing interfaces, a schema Map over runtime `Input` emits its
possible output types. An unresolved generic parameter keeps its identity:
`Map[T, int : str, ... : bytes]` emits `str | bytes`, while
`Map[T, Is[T] : str, ... : bytes]` emits only `str`. Earlier definite
matches still stop selection. Nested schema aliases expand before evaluation;
alias cycles report the authored cycle path.

## Setup

**Note:** This package isn't published on PyPI (it's not ready yet). There's already a project on PyPI called `typeforge`. It is NOT this one. I might need to pick a new name before I release this

While developing Typeforge locally, add it to another uv project as an editable dependency and install a checker:

```console
uv add --editable ../typeforge
uv add --dev pyrefly
```

Add the project configuration to `pyproject.toml`:

```toml
[tool.typeforge]
source-roots = ["src"]
output-dir = ".typeforge/stubs"
max-arity = 5

[tool.typeforge.analysis]
checker = "pyrefly"
```

Then run Typeforge directly:

```console
uv run typeforge generate
uv run typeforge check
uv run typeforge show src/example.py
```

Use the module path relative to `source-roots` when importing generated modules. If generated stubs are consumed directly by another checker, add `.typeforge/stubs` to that checker's import path.

Overlay compilation uses the shared compiler's marker validation, including class
fields and bases. Malformed expressions such as `value: Map[int]` or
`class Payload(Each[int, str]): ...` fail compilation with an adaptation error.


## VS Code 

**Note**: I only have an adapter for Pyrefly/mypy atm. The plan is adding one for each of the major type checkers, so that you can use the tool you prefer.

Install and enable the **Pyrefly** extension (`meta.pyrefly`). Point it at the Typeforge executable inside the project environment:

```json
{
  "python.languageServer": "None",
  "pyrefly.lspPath": "/absolute/path/to/project/.venv/bin/typeforge",
  "pyrefly.lspArguments": [
    "--config",
    "/absolute/path/to/project/pyproject.toml",
    "lsp",
    "--checker",
    "pyrefly"
  ]
}
```

Save this as `.vscode/settings.json`, replace both absolute paths, and reload the VS Code window. If another type-checking extension is enabled, disable its diagnostics for the workspace to avoid duplicate or conflicting results.

Typeforge proxies Pyrefly's diagnostics, hover, completion, navigation, rename, references, code actions, and semantic tokens while keeping all generated code in memory.


## Important
This is not released. There are still several things to complete before a
release, including settling the project name and hardening the integrations.

See [DESIGN.md](DESIGN.md) for the project's durable design constraints.
