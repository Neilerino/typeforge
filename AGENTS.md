# Typeforge Development Guidelines

## Project orientation

* Read `DESIGN.md` before changing compiler architecture or public semantics.
* Keep changes scoped. Do not modify `uv.lock` unless dependencies change.

## Commands

* Install the complete development environment with `uv sync --locked --all-extras --dev`.
* Use `make check` to run relevant checks: linting (Ruff and Flake8 block spacing), type checking (mypy/pyright), tests (pytest).
* Run focused checks while developing with `make check <relevant source and test paths>`.

## Design

* Keep data separate from behavior.
* Use dataclasses for structured domain data. Reuse existing values when a wrapper adds no necessary distinction, invariant, or metadata.
* Prefer functions consuming data or protocols over stateful service classes.
* Introduce abstractions that hide meaningful rules, preserve necessary distinctions, or isolate current variation and external dependencies. Prefer existing values and operations when a wrapper would only forward arguments, rename an operation, or repackage data.
* Before implementing an operation, find its existing owner and callers. Reuse or extend that implementation when the semantics match; preserve intentional differences explicitly.
* The compiler must not import or execute authored application code.
* Keep third-party frontend models behind Typeforge-owned protocols and data models.
* Generated interfaces must be deterministic and use standard Python typing constructs.
* Diagnostics must refer to authored source rather than generated implementation details.

## Typing and failures

* Use strict static typing throughout the project.
* Use the narrowest truthful return types so callers retain information the implementation already knows.
* Avoid casts and `Any` unless an integration boundary makes them unavoidable.
* Represent expected failures crossing module or public API boundaries as typed results.
* Within an implementation module, typed domain exceptions may bubble to the boundary that converts them into a result.
* Convert between exceptions and results once at a deliberate boundary; avoid repeatedly converting within the same call graph.
* Use `ok()` when a nested result should either return its value or re-raise its original failure.
* Catch only the modeled domain exceptions being converted. Unexpected exceptions must propagate.

## Implementation style

* Keep cohesive logic together. Extract functions for meaningful operations, reuse, or independent policy.
* When transforming existing data, express only what changes. Prefer `dataclasses.replace()` for same-type updates and shared traversal/rewrite functions for tree transformations.
* Use clear names; comments explain intent or constraints that the code cannot express.
* Use pattern matching for small, local decisions over domain variants.
* Prefer keyword arguments when parameter names clarify the call, especially for boolean options and similar-looking values.
* If resolving an obstacle requires changing the agreed scope or semantics, explain the tradeoff before proceeding.

## Testing and completion

* Add or update tests whenever behavior changes.
* Test failure propagation, short-circuiting, unsupported inputs, and sentinel behavior where relevant.
* Read `tests/architecture/AGENTS.md` when changing architecture tests.
* Update public documentation when public behavior or syntax changes.
* When replacing internal code, migrate its callers and remove superseded helpers, imports, and exports within the task's scope. Retained compatibility code should have an identified consumer or removal condition.
* Work is complete when the focused tests and all repository checks pass and the final diff contains no unrelated changes.
