# Architecture Test Conventions

Architecture tests describe module boundaries using the shared source model rather than
repeating paths or file-matching regexes.

## Source model

- Add package and file topology to `definitions.py`. It is the executable
  documentation for the modules covered by architecture tests.
- Define modules and files by `name` only. `ArchModule` and `ArchFile` derive their
  paths and path patterns from the module hierarchy.
- Use lists for `sub_modules` and `files` so definitions remain easy to extend.
- Export root module objects from `definitions.py`; derive nested modules, files, and
  package interfaces from them rather than exporting per-test aliases.
- Register a file or submodule in its parent module's `files` or `sub_modules` list.
  The parent relationship supplies its resolved path.

## Test composition

- Import root objects from `definitions.py` into an architecture test.
- Use pytest fixtures for shared setup, isolation, or cleanup. Read immutable
  topology values directly from the shared roots, such as
  `SEMANTICS.mod("domain")`, `SEMANTICS.file("protocols")`, or
  `SEMANTICS.interface`.
- Derive paths and matchers from the source model: the project root from
  `TYPE_FORGE.path.parent` and an external boundary with
  `TYPE_FORGE.files_outside(SEMANTICS)`.
- Use an `architecture` fixture to translate the root module into a fresh
  `LayeredArchitecture` by iterating its `.layers` collection and registering each
  `.layer(...).defined_by(...)` mapping.
- Keep each rule focused on its dependency policy; the source model derives the
  layer mappings, so topology is maintained only in `definitions.py`.
- A rule-specific matcher, such as an external dependency allowlist, may remain next
  to the rule when it is not a source-module definition.

## Extending a boundary

When a source package gains a relevant file or child package, update its definition
before writing or changing the architecture rule. Run the focused architecture test,
then follow the repository-level validation requirements in the root `AGENTS.md`.
