# Typeforge

Typeforge compiles richer type relationships from normal Python source into portable `.pyi` files or ephemeral checker overlays.

```python
from typeforge import Case, Collect, Default, Each, Map


def collect[T](*values: Each[T]) -> Collect[T]: ...


def serialize[T](value: T) -> Map[
    T,
    Case[int, float],
    Case[bytes, str],
    Default[T],
]: ...
```

## Try the prototype

```console
uv sync --all-extras
uv run typeforge --config examples/prototype/pyproject.toml generate
uv run typeforge --config examples/prototype/pyproject.toml show examples/prototype/src/api.py
uv run typeforge --config examples/prototype/pyproject.toml check --checker mypy
uv run typeforge --config examples/prototype/pyproject.toml check --checker pyrefly
```

Generated stubs are written to `examples/prototype/.typeforge/stubs`.

## Configuration

```toml
[tool.typeforge]
source-roots = ["src"]
output-dir = ".typeforge/stubs"
max-arity = 5

[tool.typeforge.analysis]
checker = "mypy"
# command = ["mypy"]
```

Run `typeforge generate` to compile configured source roots or `typeforge generate PATH` for selected files. `typeforge show PATH` prints a generated stub without writing it.

`typeforge check [PATH ...]` transforms each selected source file ephemerally and runs the configured checker. This gives mypy and Pyrefly precise Typeforge types inside the implementation file itself without changing it or writing a project stub. Install the matching `typeforge[mypy]` or `typeforge[pyrefly]` extra.

For editor integration, configure an LSP client to launch:

```console
typeforge --config pyproject.toml lsp --checker pyrefly
```

The proxy keeps authored and transformed documents in memory, forwards the transformed text to Pyrefly under the original URI, and maps diagnostics and hover ranges back to authored source. It advertises only synchronized documents, diagnostics, and hover until more position-sensitive LSP features are mapped. Mypy has no LSP server; its default adapter passes transformed text directly to mypy's build API with cache writes disabled. Configuring an external mypy command selects the official shadow-file compatibility path.

### VS Code

Install the `meta.pyrefly` extension and point its language-server hook at the Typeforge executable installed in the project environment:

```json
{
  "mypy-type-checker.ignorePatterns": ["**"],
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

Reload the VS Code window after changing the workspace settings. Disabling the Python extension's language server prevents Pylance diagnostics from competing with Typeforge without changing standalone Pyright configuration. The mypy extension's workspace ignore prevents duplicate mypy diagnostics without disabling that extension globally. Python's normal grammar continues to provide syntax colors, while Typeforge maps Pyrefly diagnostics, hover, completion, navigation, symbols, inlay hints, references, rename edits, code actions, folding ranges, hierarchies, and semantic tokens back to authored source.

The generated directory must also be on each checker's import path:

```toml
[tool.mypy]
mypy_path = ".typeforge/stubs"

[tool.pyright]
extraPaths = [".typeforge/stubs", "src"]
```

Imports must use the module path relative to `source-roots`. With `source-roots = ["src"]`, import `api`, not `src.api`; the generated stub shadows `api.py`.

## Implemented syntax

* `Each` and `Collect` for heterogeneous variadic capture;
* `If` with `Equal`, `Assignable`, `All`, `Any`, and `Not`;
* finite `Map` expressions with `Case` and `Default`;
* structural `Map` cases where `Value` captures a nested generic argument;
* `MapFields` over named `TypedDict`s with `Field`, `OptionalField`, `ReadonlyField`, `Drop`, `Key`, and `Value`.

```python
type QueryResult[T] = Map[
    T,
    Case[Option[Value], Value | None],
    Default[T],
]


def query[T](
    *components: Each[type[T]],
) -> tuple[*Collect[QueryResult[T]]]: ...
```

The runtime helpers are inert aliases. Functions, classes, and values are never wrapped.
Library consumers do not run the compiler; they may receive the lightweight marker package as a transitive dependency.

## Prototype boundaries

The prototype targets Python 3.14. It preserves ordinary classes, bounded generics, decorators, fields, methods, public variables, and runtime-only main guards. Enriched methods are lowered inside their owning class.

`MapFields` specializes named `TypedDict`s visible during generation; unknown downstream records receive an `object` fallback. Structural `Map` cases and heterogeneous variadics use a configured finite arity frontier followed by a less precise portable fallback.

Typeforge refuses to generate a shadow stub when a module contains a public declaration it cannot preserve. Plain imports are not yet supported; use `from` imports while prototyping.

See [PROJECT_GOAL.md](PROJECT_GOAL.md) for the project direction.
