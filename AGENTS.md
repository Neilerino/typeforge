# Typeforge Development Guidelines

## Project orientation

* Typeforge is a Python 3.14 package managed with `uv`.
* Read `DESIGN.md` before changing compiler architecture or public semantics.
* Source lives under `src/typeforge`; tests mirror the source areas under `tests`.
* Keep changes scoped. Do not modify `uv.lock` unless dependencies change.

## Commands

* Install the complete development environment with `uv sync --locked --all-extras --dev`.
* Use `make check` to run relevant checks: linting (Ruff and Flake8 block spacing), type checking (mypy/pyright), tests (pytest).
* Run focused checks while developing with `make check <relevant source and test paths>`.

## Design

* Keep data separate from behavior.
* Represent domain data with dataclasses.
* Prefer functions consuming data or protocols over stateful service classes.
* Consider dependancy seams between modules, and how modules should relate to each other.
* The compiler must not import or execute authored application code.
* Keep third-party frontend models behind Typeforge-owned protocols and data models.
* Generated interfaces must be deterministic and use standard Python typing constructs.
* Diagnostics must refer to authored source rather than generated implementation details.
* Prefer calling with kwargs to better self document the code, unless a function has 2 or fewer parameters or if the names are obvious

## Typing and failures

* Use strict static typing throughout the project.
* Avoid casts and `Any` unless an integration boundary makes them unavoidable.
* Represent expected failures crossing module or public API boundaries as typed results.
* Within an implementation module, typed domain exceptions may bubble to the boundary that converts them into a result.
* Convert between exceptions and results once at a deliberate boundary; avoid repeatedly converting within the same call graph.
* Use `ok()` when a nested result should either return its value or re-raise its original failure.
* Catch only the modeled domain exceptions being converted. Unexpected exceptions must propagate.

## Implementation style

* Prefer clear names and small functions over explanatory comments.
* Add comments only when intent cannot be expressed through structure or naming.
* Use pattern matching for small, local decisions over domain variants.
* Don't rush to complete a task; If while your working on a task you encounter an obstacle, take a step back and we can regroup.

## Testing and completion

* Add or update tests whenever behavior changes.
* Test failure propagation, short-circuiting, unsupported inputs, and sentinel behavior where relevant.
* See `tests/architecture/AGENTS.md` for details on architecture testing.
* Update public documentation when public behavior or syntax changes.
* Work is complete when the focused tests and all repository checks pass and the final diff contains no unrelated changes.
