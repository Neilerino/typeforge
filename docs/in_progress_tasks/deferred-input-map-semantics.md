# Deferred `Input` Map Semantics

Status: Complete
Depends on: Parameterized type pattern semantics

## Goal

Represent a valid `Map[Input, ...]` as deferred semantic meaning when no input is
bound. Calculate its possible output type once in shared semantics. Leave
Pydantic validation-plan construction to the Pydantic integration.

## Contract

Given:

```python
Map[
    Input,
    Case[int, int],
    Case[str, UUID],
    Default[bytes],
]
```

`evaluate()` returns a `DeferredMap` that preserves:

- authored case order;
- each case test and output;
- the optional default;
- the current `EvaluationContext`;
- `int | UUID | bytes` as its possible output type.

Without a default, no-match remains a failure and does not add `Never` to the
possible output type. An unbound `Input` outside a supported deferred `Map`
remains `UnboundInputSemanticError`.

`DeferredMap` contains semantic data only. Raw input values, `CoreSchema`,
validators, serializers, dispatch tags, JSON Schema, and Pydantic strategy stay
in the Pydantic integration.

## Steps

1. Detect an unbound `InputReference` subject before ordinary `Map` evaluation.
   Return the existing unbound-input failure for unsupported `Input` positions.

   Completion criterion: semantics distinguishes a valid deferred `Map` from an
   invalid unbound `Input`.

2. Evaluate every case output and the optional default without selecting a case.
   Require each possible output to resolve to a type and preserve modeled
   failures unchanged.

   Completion criterion: invalid output roles and adapter failures cross the
   semantic seam as their original `SemanticIssue`.

3. Normalize possible outputs through `TypeSystem.union()` and construct
   `DeferredMap` with the authored cases, default, context, and normalized
   `ResolvedType`.

   Completion criterion: defaults are included, no-match is excluded, and
   duplicate or `Never` members follow the adapter's union rules.

4. Add coverage for normalization, adapter failure propagation, nested context,
   output expressions that depend on unbound `Input`, and bound `Input` behavior.
   Remove the two strict deferred-map `xfail` markers in
   `tests/unit/semantics/test_migration_spec.py`.

   Completion criterion: all deferred-map contract tests pass without Pydantic
   imports or Pydantic execution data in `typeforge.semantics`.

## Deferred decision

A later task must define how a runtime integration resumes a `DeferredMap` when
input becomes available. The decision must state whether selection observes only
the input type or also the raw value. The current migration slice only preserves
deferred meaning and calculates its possible output type.
