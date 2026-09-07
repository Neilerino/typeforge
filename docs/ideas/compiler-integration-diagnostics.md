# Compiler Integration Diagnostics

Status: Idea — follow-up after the first Pydantic redesign pass

Related work: [Pydantic integration redesign](../in_progress_tasks/pydantic-integration-redesign.md)

## Intended outcome

Add a plugin-style compiler extension mechanism for integration-specific static
checks. The first consumer would model Typeforge's Pydantic integration so that
statically detectable failures appear as authored-source type diagnostics before
schema construction or value validation raises an exception.

For example, an unparametrized model may supply typing.Any as a Map subject under
Pydantic's generic fallback policy. If no case matches and the Map has no default,
the integration raises an exception. A compiler integration could report that
failure earlier when the relevant model use and type arguments are known.

## Design constraints to carry forward

- Consume shared semantic rules and the Pydantic integration's documented
  contracts rather than creating another Map evaluator.
- Reuse policy within typeforge.pydantic, separate from its schema emission.
  Adapt source-derived generic facts and semantic outcomes into that interface
  rather than duplicating its rules.
- Guard optional integration imports: if Pydantic is unavailable, do not load
  its compiler plugin. When installed, the plugin may import the integration
  package. Handle missing optional dependencies specifically without hiding
  unrelated import failures. Test both dependency-present and dependency-absent
  loading; no separate dependency-free policy package is required.
- Classify typed outcomes before diagnostic presentation. Preserve no-match
  evidence separately from an explicitly selected Never output and attach
  authored spans in the compiler adapter, not in shared semantic or policy data.
- Keep integration-specific generic fallback and diagnostic policy distinct from
  general compiler typing and emission. Do not globally replace a compiler Never
  result with an error merely because one runtime integration rejects that use.
- Preserve the distinction between a valid generic declaration, a valid concrete
  specialization, and an invalid unparametrized use. Diagnostics belong at the
  authored location where the failure can be established.
- The compiler must continue to analyze source without importing or executing
  authored application code. Loading the installed Pydantic integration does not
  authorize importing application models or running runtime schema generation
  to perform static checks.
- Report only failures justified by available static information. Runtime Input
  dispatch can still require per-value checks; static diagnostics supplement
  runtime validation rather than replacing it.

The plugin interface, registration/configuration mechanism, analysis stage, and
delivery through supported type checkers remain to be designed. This idea does
not prescribe a public plugin API or a checker-specific plugin implementation.

## First-pass preparation

The Pydantic redesign should retain modeled failure categories, authored
diagnostics, and executable behavior contracts, including Any/no-default cases.
Those contracts provide evidence for later static checks. No plugin registry,
compiler hooks, or static diagnostic implementation is required in that pass.
The first pass keeps reusable integration rules separate from schema emission
inside the Pydantic package. Guarded plugin loading is implemented in this
follow-up, without restructuring the runtime package for dependency-free imports.
