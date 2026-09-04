# Mission: Specification-Based Test-Driven Development

## Why
Define Typeforge feature boundaries and intended outcomes before implementing their logic. Use executable specifications and a deliberate `xfail` workflow to keep planned behavior visible while preserving confidence during compiler refactors.

## Success looks like
- Turn a feature idea into explicit rules, examples, counterexamples, and open questions.
- Choose a stable Typeforge boundary at which each outcome can be observed.
- Encode agreed behavior as strict expected-failure contracts without coupling tests to incidental implementation.
- Drive one small contract from genuine failure to passing behavior, then refactor safely.

## Constraints
- Apply the practice directly to Typeforge's Python 3.14, pytest, and `uv` workflow.
- Preserve Typeforge's authored-source diagnostics, deterministic output, typed failures, and dependency seams.
- Keep lessons short, interactive, and grounded in real repository examples.

## Out of scope
- Formal verification and proof systems.
- Adopting a separate Gherkin or Cucumber test stack.
