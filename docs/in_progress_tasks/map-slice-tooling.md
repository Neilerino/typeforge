# Slice Map diagnostics and tooling

Slice 10 evidence, 2026-09-07. See the [migration contract](map-slice-syntax-contract.md)
and [union support boundaries](map-slice-union-findings.md).

## Authoring forms

```python
from typing import Literal

from typeforge import Assignable, Map

type Selected[T] = Map[
    T,
    Literal["text"]: str | None,
    Assignable[bytes]: bytes,
    ...: T,
]
type Nested[T] = list[Map[T, int: str, ...: bytes] | None]
type Empty[T] = Map[T, :]
```

Use Literal for string selectors, including unary predicate targets. Python accepts
bare strings in slices, but Ruff currently treats them as forward references in
type aliases and reports F821. Typeforge rejects that spelling with
`Map string selectors require Literal["text"]`. Supporting it later requires
positive formatter, linter, and checker-integration evidence without suppressions.

Ruff may format simple branches as `int:str` and empty endpoints as `:`. These are
valid spellings. Spaces are not semantic; grouping and order are. Existing maximum
line length and lint rules stay in effect. Empty endpoints mean None, and `...:`
is a fallback to None. A third non-None slice endpoint is invalid.

## Verified toolchain

[Executable probes](../../tests/unit/test_slice_tooling.py) use these installed
versions; this is evidence for the tested toolchain, not all editor highlighters:

| Tool | Version | Result |
| --- | --- | --- |
| Python tokenizer and AST parser | 3.14.3 | Accept the supported examples, including nested unions and empty endpoints. |
| Ruff formatter and linter | 0.15.21 | Formatting preserves the complete AST; the formatted fixture passes the repository's configured lint rules. A separate negative probe detects F821 for bare strings. |
| mypy | 2.2.0 | Raw slices require projection. The overlay passes strict checking and rejects an incorrect implementation return. |
| Pyright | 1.1.411 | Raw slices require projection. The overlay passes standard checking and rejects an incorrect implementation return. |
| Pyrefly | 1.1.1 | With explicit configuration, raw slices require projection. The overlay passes and rejects an incorrect implementation return. |

Raw Python validity does not make subscription slices ordinary checker type
arguments. Use Typeforge's checker integrations for authored modules or generated
stubs for consumers. Existing compiler support limits still apply, including the
single type parameter required by callable relationship aliases. These probes do
not add support for otherwise unsupported relationships.

## Diagnostic presentation

[Diagnostic regressions](../../tests/unit/test_slice_diagnostics.py) cover:

- Branch arity and entry errors using `selector: output` and `...: output`.
- Runtime schema and deferred validation errors displaying Map slices instead
  of internal Case/Default branches, while retaining codes, phases, subjects,
  raw input values, and Pydantic field locations.
- Nested union-branch syntax errors retaining authored UTF-8 spans, and predicate
  alias failures retaining the authored literal expression.
- Annotation display traversing nested typing structures and Callable parameter
  lists while keeping aliases opaque and Literal/Annotated payloads unchanged.

Runtime display reconstructs a readable expression from normalized typing data.
It cannot recover original whitespace, import renames, or an omitted None endpoint;
already-bound unary predicates may appear with both operands. Rendering does not
evaluate alias bodies, interpret metadata, or alter semantic outcomes.

Definite no-match, speculative alternatives, and unsupported representations keep
their existing error boundaries. The union and field suites retain their separate
rejection and provenance assertions; presentation changes do not clear G1–G6.
