# Typeforge error architecture

## Status

Idea for future work. This document does not describe the current package contract.

## Context

Typeforge currently models failures in two distinct ways:

- Raised exceptions such as `SemanticIssue`, `SchemaIssue`, `EvaluationError`, and `LspError`.
- Immutable failure data returned through `Result`, such as `AnalysisError`, `CliError`, `OverlayError`, and `DocumentationError`.

Module-specific exception families provide precise error codes and allow narrow catches at deliberate seams. However, there is no common root for modeled exceptions raised by Typeforge. A package-level root could make final error handling and future tooling more consistent without replacing those module-specific families.

## Proposed direction

Add a focused `typeforge.errors` module containing a minimal root exception:

```python
class TypeforgeError(Exception):
    """Base for modeled exceptions raised by Typeforge."""
```

Raised exception families would inherit from this root while retaining their own data and code contracts:

```python
@dataclass(frozen=True, slots=True)
class SemanticIssue(TypeforgeError):
    message: str

    code: ClassVar[SemanticIssueCode]
```

The intended hierarchy would be similar to:

```text
TypeforgeError
├── SemanticIssue
│   ├── ExpectedTypeSemanticError
│   └── ...
├── SchemaIssue
├── EvaluationError
├── LspError
└── ...
```

Use `TypeforgeError` rather than `TypeForgeException`: `Error` follows Python convention, and `Typeforge` matches the project name.

Keep this in `typeforge.errors` rather than a general `core` module. A narrowly named foundational module is less likely to become a miscellaneous dependency hub.

## Keep the root minimal

Initially, `TypeforgeError` should be a marker base only. It should not require every exception to expose the same fields.

Existing exception families carry different contextual data, including paths, authored expressions, phases, and declarations. Requiring fields such as `code` at the root could force meaningless defaults or unnecessary normalization. Each module-specific base should continue to define the strongest contract valid for that module.

## Catching policy

Internal modules should continue to catch only the narrowest modeled exception family they deliberately convert:

```python
try:
    ...
except MarkerNormalizationError as error:
    raise AdaptationError(...) from error
```

Broadly catching `TypeforgeError` inside normal module flow could hide a missing translation between modules or erase useful failure types.

Catching `TypeforgeError` is appropriate only at a genuine package-level seam, such as:

- A top-level imperative facade
- The CLI entry point
- A server request handler
- A final logging or crash-reporting layer
- A public operation documented to normalize all Typeforge exceptions

At such a seam, the root can support one deliberate conversion into a public failure result. Unexpected exceptions must continue to propagate.

## Failure data remains separate

Types such as `AnalysisError`, `CliError`, `OverlayError`, and `DocumentationError` are immutable failure values returned through `Result`; they are not raised exceptions. They should not inherit from `TypeforgeError` merely to create uniformity.

The distinction should remain explicit:

- Exception inheritance provides catchability for raised, modeled failures.
- Result failure data provides typed values at module and public seams.

## Future serialization

Serialization is broader than exception inheritance because both exceptions and Result failure values may need presentation or transport. Model that capability structurally with a protocol and a free function rather than adding serialization behavior to `TypeforgeError`:

```python
class CodedFailure(Protocol):
    @property
    def code(self) -> StrEnum: ...

    @property
    def message(self) -> str: ...


class SerializedFailure(TypedDict):
    domain: str
    code: str
    message: str


def serialize_failure(
    domain: str,
    failure: CodedFailure,
) -> SerializedFailure:
    return {
        "domain": domain,
        "code": failure.code.value,
        "message": failure.message,
    }
```

Serialized failures should include a domain or namespace because code values can overlap across modules. For example:

```json
{
  "domain": "semantics",
  "code": "expected_type",
  "message": "Equal operands must both be types"
}
```

Class names should not be treated as stable serialized identifiers.

## Potential implementation sequence

1. Add the minimal `typeforge.errors.TypeforgeError` marker.
2. Make modeled, raised Typeforge exception families inherit from it.
3. Preserve module-specific roots and code enums.
4. Keep Result failure values separate from the exception hierarchy.
5. Add a package-level catch only when a concrete caller needs one.
6. Design a structural serialization contract when there is a real serialization consumer.
7. Document the public catch and serialization guarantees before treating them as stable interfaces.

## Non-goals

- Creating one global error-code enum.
- Catching all Typeforge failures inside every higher-level module.
- Turning all Result failure values into exceptions.
- Adding placeholder codes solely to satisfy a root contract.
- Introducing serialization before its wire format and consumers are understood.
