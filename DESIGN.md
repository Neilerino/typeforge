# Typeforge Design

Typeforge is an authoring layer and compiler for Python typing. It targets existing type checkers rather than replacing them.

## Principles

- Authored source remains valid Python.
- Runtime markers are inert and add no overhead to application call paths.
- The compiler parses source without importing or executing user code.
- Generated output uses standard typing constructs understood by existing checkers.
- Diagnostics refer to authored source rather than generated implementation details.

## Complete interfaces

A `.pyi` file replaces its corresponding implementation as the module interface seen by a type checker. Typeforge must therefore preserve the complete public interface of every module it shadows. If it cannot safely preserve a declaration, generation must fail instead of silently omitting it.

## Honest expressiveness

Some relationships can be expressed directly with standard generics. Others can only be lowered over known types, literals, fields, or argument counts.

Finite specialization must remain explicit. Typeforge should provide a documented fallback, require local specialization, or report that a relationship cannot be represented portably. It must not present a configured finite frontier as an open-ended generic capability.

## Library and project output

Published library stubs must be deterministic from library source and configuration. Consumer call sites must never influence them, and consumers should not need to run the Typeforge compiler.

Project integrations may use local context to improve precision. These transformations remain in memory, never rewrite authored files, and are not publishable by default.

## Explicit record semantics

`TypedDict`, dataclasses, protocols, ordinary classes, attrs classes, and validation models have different construction, inheritance, and mutation semantics. Typeforge must support each family through an explicit adapter rather than treating every annotated object as the same kind of record.
