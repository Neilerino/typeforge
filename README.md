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

Reusable unary predicate aliases bind to the subject of the consuming Map in
both compiler and Pydantic frontends:

```python
from typeforge import Assignable, Map

type Numeric = Assignable[int]
type Encoded[T] = Map[T, Numeric: str, ...: bytes]
```

Generic predicate aliases such as `type Is[T] = Equal[T]` and compounds using
`All`, `Any`, and `Not` follow the same rule. Nested Maps bind their own subjects;
explicit binary operands stay explicit. A unary predicate used outside a selector
fails as unbound. Existing union restrictions still apply.

The syntax migration is in progress: inline checker
projection still has work remaining. Raw slice annotations
are not promised to work in ordinary type checkers. Existing Case/Default
examples below remain valid during the repository migration and will be removed
at the coordinated cutover. See the
[migration checklist](docs/in_progress_tasks/map-slice-syntax.md) and
[union limitations](docs/in_progress_tasks/map-slice-union-findings.md).

```python
from typeforge import Case, Default, Map


def serialize[T](value: T) -> Map[
    T,
    Case[int, float],
    Case[str, bytes],
    Default[T],
]:
    ...

result_1 = serialize(5) # float
result_2 = serialize("test") # bytes
result_3 = serialize([123]) # list[int]
```

Each `Case` test can be an exact or structural type pattern or a boolean
predicate composed with `Equal`, `Assignable`, `All`, `Any`, and `Not`. Cases
share one declaration order, and the first matching pattern or true predicate
wins.

Choose a return type from a boolean flag:

```python
from typing import Literal

from typeforge import Case, Default, Equal, Map


type FetchResult[T: bool] = Map[
    T,
    Case[Equal[T, Literal[True]], dict[str, object]],
    Default[bytes],
]

def fetch[T: bool](
    url: str,
    *,
    parse_json: T,
) -> FetchResult[T]:
    ...


data = fetch("/users", parse_json=True)   # dict[str, object]
raw = fetch("/users", parse_json=False)   # bytes
```

Capture and reuse the inner type of a generic wrapper:

```python
from typeforge import Case, Default, Map, Value


class Option[T]:
    value: T


type QueryResult[T] = Map[
    T,
    Case[Option[Value], Value | None],
    Default[T],
]


def unwrap[T](value: T) -> QueryResult[T]:
    ...


option: Option[int]
result = unwrap(option)  # int | None
```

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

## Pydantic integration

Install the optional Pydantic extra, then wrap a Typeforge expression in
`Schema[...]`:

```console
pip install "typeforge[pydantic]"
```

```python
from typing import Literal, TypedDict

from pydantic import BaseModel
from typeforge import Case, Default, Drop, Equal, Field, Key, Map, MapFields, Value
from typeforge.pydantic import Schema


class User(TypedDict):
    name: str
    password: str


type Public[T] = MapFields[
    T,
    Map[
        Key,
        Case[Equal[Key, Literal["password"]], Drop],
        Default[Field[Key, Value]],
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

### Generic model fields

`Schema` works on ordinary generic `BaseModel` fields, including nested containers
and aliased Typeforge expressions. Pydantic owns specialization, inheritance,
field configuration, validators, serializers, and `model_rebuild()`:

```python
from pydantic import BaseModel
from typeforge import Case, Map
from typeforge.pydantic import Schema


class Payload[T](BaseModel):
    value: Schema[Map[T, Case[int, str], Case[bytes, int]]]


assert Payload[int](value="3").value == "3"
assert Payload[bytes](value="3").value == 3
```

Unparametrized fields follow Pydantic's fallback order: a type default, constraints,
a bound, then `typing.Any`. Typeforge applies transformations to that fallback
while preserving Pydantic's validation and serialization behavior for TypeVars.
It never infers an omitted model type argument from submitted values.

For a static Map, `Any` matches an exact `Any` case but does not match `int` or
invent structure for `list[Value]`. A known `list[Any]` can capture `Any`.
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
from typeforge import Case, Default, Map
from typeforge.pydantic import Input, Schema


adapter = TypeAdapter(Schema[Map[Input, Case[str, int], Default[float]]])
assert adapter.validate_python("3") == 3
assert type(adapter.validate_python(3)) is float
```

Input dispatch selects the first matching case before output coercion. For
example, `"bad"` selects the `int` output above and fails integer validation;
validation does not retry another case or the default. Nested Maps see the same
raw value until output validation begins, while Input inside a container's item
schema observes each item.

Supported tests include exact Python types, unions, `Annotated` wrappers,
`Literal` values, `Input` as a catch-all, and `Equal`, `Assignable`, `All`, `Any`,
and `Not` predicates. Exact type tests distinguish `bool` from `int`; use
`Assignable` to accept subclasses. Literals compare both type and value:
`Literal[1]` does not match `True`, `1.0`, or an integer enum member. Annotation
validators are not executed to choose a case.

Parameterized value-time patterns such as `list[int]` and `list[Value]` fail
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
`Map[T, Case[int, str], Default[bytes]]` emits `str | bytes`, while
`Map[T, Case[Equal[T, T], str], Default[bytes]]` emits only `str`. Earlier definite
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
