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

For local `Map` and `If` implementations, Typeforge also verifies return expressions after recognizable `type`, `isinstance`, literal, `None`, boolean, and `match` guards. It emits ordinary typed assignments in memory and lets the configured checker infer the expression type. Unrecognized flow falls back to the safe aggregate return type.

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

Choose a return type from a boolean flag:

```python
from typing import Literal

from typeforge import Equal, If


type FetchResult[T: bool] = If[
    Equal[T, Literal[True]],
    dict[str, object],
    bytes,
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
from typeforge import Drop, Equal, Field, If, Key, MapFields, Value
from typeforge.pydantic import Schema


class User(TypedDict):
    name: str
    password: str


type Public[T] = MapFields[
    T,
    If[
        Equal[Key, Literal["password"]],
        Drop,
        Field[Key, Value],
    ],
]


class Response(BaseModel):
    user: Schema[Public[User]]
```

Pydantic compiles this to a native typed-dictionary core schema, and validation
returns an ordinary `dict`; `Schema` is not a value wrapper. Schema-time `Map`
and `If` expressions add no Typeforge Python calls during validation. Expressions
using `typeforge.pydantic.Input` intentionally dispatch on each raw input value
before letting the selected Pydantic schema validate it.

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
