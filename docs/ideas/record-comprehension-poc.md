# Type-function record comprehension POC

Verdict: the selected syntax is feasible for a constrained type-function body.
The exact password-dropping example works through a prototype compiler adapter
and the Pydantic Schema integration. Existing Map evaluation, record data, stub
emission, and Pydantic field-schema emission are reusable. This requires changes
beyond AST normalization; it is not an implementation of the public feature.

Follow-up: the [approved-API derisking report](type-function-derisking.md) exercises
the subsequently agreed named captures, generic aliases, field edits and callable
contracts. Its findings supersede this POC's historical open-policy notes.

## Syntax tested

```python
@type_function
def Public[T]():
    return Record(
        Map[
            field.name,
            Literal["password"]: Drop,
            ...: field,
        ]
        for field in Fields[T]
    )

type PublicUser = Public[User]
```

The runtime probe defines the function in an in-memory module with a synthetic
filename, without inspect, source-file access, or bytecode interpretation.
The compiler probe reads the same fixture as source and never imports or executes
it. An appended module-level exception does not affect compilation.

## Construction model demonstrated

At runtime, the decorator executes the construction body once while T is still a
TypeVar. Fields[T] yields one symbolic field during Record construction. Record
consumes the generator immediately and stores its source and transformation as an
immutable template. No live generator is retained or replayed on specialization.
A context-local collector retains the source even when the output is always Drop.

The decorator returns a generic TypeAliasType containing the template annotation.
Public[User] and an ordinary forwarding alias specialize normally. The POC's
runtime annotation hook supplies the concrete record to existing reflection,
shared Map evaluation, and Pydantic schema emission. Ordinary validation does not
execute the authored function or comprehension.

This runtime construction executes authored Python once. The subsequently
[agreed runtime boundary](map-selection-decisions.md#runtime-construction-and-compiler-support)
keeps compilation optional and separates runtime template validity from compiler
source support. The compiler enforces its supported syntax without execution.
Symbolic truthiness is rejected in the runtime POC; identical rejection of every
additional Python statement is not required by the agreed contract.

The compiler prototype recognizes decorated definitions, local selector aliases,
the generator binding, and direct concrete applications such as Public[User] and
Listed[A | B]. It normalizes field.name/type to contextual references and lowers
the transform through the existing source parser and semantic adapter. It then
uses existing record-shape discovery and TypedDict/stub emission. This is a
separate adapter experiment, not wiring into compile_source or the editor proxy.

## Evidence

All 17 core probes and two follow-up generic probes pass on Python 3.14.3 using
the checkout's installed dependencies. Full repository `make check` also passes.

| Case | Evidence |
| --- | --- |
| Exact selected syntax | Compiler output and Schema validation omit password. |
| Returning field | Optional, readonly, and combined optional-readonly flags survive in both paths. |
| Explicit field construction | Renaming and OptionalField coexist with passthrough fields. |
| Record union | Listed[A-or-B] yields two complete records; both checkers and strict runtime validation reject a mixed shape. |
| Empty record / all Drop | Empty outputs work; all-Drop construction retains its source. |
| Repeated specialization | Six schema builds over different records do not rerun type-function bodies. |
| Local alias | A local Literal selector alias works in both paths. |
| Generic alias composition | A forwarding Wrapped[T] = Public[T] works at runtime. |
| Field metadata | Annotated MinLen is retained, appears in JSON Schema, and rejects invalid runtime input. |
| Failure paths | Duplicate names and unsupported record members are rejected in the runtime prototype. |
| Unsupported comprehension filter | Compiler prototype reports the authored line and column. |
| Ordinary checking | mypy and Pyright accept positive consumers and reject password, readonly-write, and correlated-union violations. |
| Pydantic lifecycle | Concrete and generic model specialization/rebuild probes pass. |
| Type parameter in output | Explicit template substitution makes Field[field.name, T] validate T rather than silently accepting arbitrary values. |

For the record-union probe, A has x:int/y:str and B has x:bytes/y:float.
Listed produces x:list[int]/y:list[str] or x:list[bytes]/y:list[float].
The rejected mixed example is x:list[int]/y:list[float].

## Required representation and integration changes

1. **Reusable template and parameter bindings.** Opaque template objects hide
   TypeVars from Python's normal substitution. The initial POC incorrectly accepted
   scalar values where its output required T. Explicit identity-based parameter
   substitution fixed that runtime probe. Production should extend the existing
   binding owner rather than introduce competing substitution rules.
2. **Current-field reference.** Existing Key/Value references cannot represent
   returning an entire field. Replacing field with Field[Key, Value] would reset
   optional/readonly flags. The POC uses a private sentinel and returns the original
   RecordField; production needs a deliberate field-reference operation and scope.
3. **Record alternatives.** The POC transforms each union member independently
   and retains a tuple of complete RecordShapes until emission. Current MapFields
   evaluation does not provide this distribution. Integrate it at the shared
   record-transform owner; do not flatten Fields[A | B] into one field stream.
4. **Generic runtime fallback.** Initially an unspecialized Pydantic generic model
   failed at class definition. Reusing the existing rejecting generic fallback
   permits definition and later specialization without accepting values while the
   required record shape is unknown. Bounded and constrained parameters need more
   coverage before generalizing this route.
5. **Production source and projection plumbing.** Add function recognition, local
   binding scope, applications, complete module publication, and authored origins.
   The POC verifies AST-local diagnostics and generated checker interfaces; it
   does not establish editor navigation, hover, or full diagnostic remapping.

The prototype's small record-transform loop is an extension seam, not evidence
that the current evaluator already supports the syntax unchanged. Map selection
itself remains owned by shared semantics. Existing backend record models and
emitters were sufficient for the concrete output shapes tested.

## Limits and decisions still needed

- Compiler coverage is one type parameter, named TypedDict applications/unions,
  local non-generic selector aliases, and one unfiltered generator. It does not
  prove arbitrary generic publication or a general type-function interpreter.
- Named structural captures, nested field scopes, recursion, multiple generators,
  filters, arbitrary calls/control flow, and bounds/constraints remain outside the
  demonstrated subset. The syntax alone does not provide their semantics.
- Runtime field metadata was tested; full record-level metadata, inheritance,
  generic record families, cross-module aliases, and stable generated naming need
  broader integration coverage. No new record family is implied by Record.
- The POC provisionally rejects unsupported union members and preserves original
  fields on passthrough. These are exercised candidate policies, not additional
  user approvals for all pending record semantics.
- Record unions remain a required derisking area during implementation despite
  this successful concrete witness. Callable match precision and overlapping
  structural captures remain separate open design questions.

Recommendation: proceed to a scoped implementation specification for this form.
Retain the existing field-transform machinery internally, adding the required
bindings/reference and alternative handling. Decide public MapFields migration
when the replacement is ready; the POC changes no public APIs.

## Reproduction and source checkpoint

The throwaway source and its generated artifacts are committed in a **separate
local prototype repository**, not a branch in the Typeforge checkout:

- Retained repository:
  `/Users/neilwadden/.codex/visualizations/2026/09/07/01a07d18-ce62-7e82-bf3c-06a7362ad7d9/type-function-poc`
- Branch: `neil/record-comprehension-poc`
- Commit: `1f19047`
- Entry point: `verify.py`
- Evidence: `results.json`, `limits-before.json`, `limits.json`, `generated.pyi`,
  `mypy.txt`, and `pyright.txt`.

```sh
/Users/neilwadden/Programming/typeforge/.venv/bin/python \
  /Users/neilwadden/.codex/visualizations/2026/09/07/01a07d18-ce62-7e82-bf3c-06a7362ad7d9/type-function-poc/verify.py
```

The original working copy was in `/tmp/typeforge-type-function-poc`; the retained
clone above was rerun successfully and does not depend on that temporary copy.
The committed README records the original working location; use the command above
for the retained clone. This report captures the validated findings in the main
checkout. The existing user changes to the union matrix were not modified.
