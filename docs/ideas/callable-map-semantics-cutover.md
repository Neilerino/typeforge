# Callable Map Semantics Cutover

Status: Idea — Pydantic redesign prerequisite complete; callable cutover remains deferred

Related work: [Pydantic integration](../../README.md#pydantic-integration)

## Motivation

Production compiler Schema boundaries and MapFields evaluation now consume
shared semantics. The completed eight-slice compiler migration removed the
legacy Schema evaluator and its unused IR. Callable Map relationships still
follow a separate `MapType` path through compiler specialization.

That path contains language decisions as well as compiler mechanics. In
`src/typeforge/compiler/specialization/_lowering.py`, `map_specializations()`,
`map_default_output()`, `_map_output_for_input()`, and
`_resolve_predicate_for_input()` derive candidates, select ordered outputs,
resolve defaults, and evaluate predicates. Structural overload construction also
substitutes `Value` into input and output expressions.

Some of these rules overlap shared evaluation; others describe the finite
relationships Python typing can express. Characterize that distinction before
moving code. The completed Schema cutover did not unify callable evaluation.

## Intended outcome

Shared semantics determines the meaning of callable Map expressions for the
inputs considered by specialization. The compiler determines how to represent
that relationship as standard Python typing, including overloads, generic
signatures, finite arity expansion, and honest fallback behavior.

The compiler continues to own:

- source adaptation, authored diagnostics, and origin tracking;
- specialization candidate discovery and representability limits;
- overload ordering and emission where dictated by checker constraints;
- Each/Collect expansion and type-variable substitution for emitted signatures;
- implementation verification and its control-flow analysis;
- publication versus project-overlay policy.

Backend equality, assignability, and type construction remain behind the
compiler's TypeSystem adapter. Reuse an existing operation when its semantics
match; record intentional differences rather than forcing them through a common
helper. This is not a proposal to move the specialization module wholesale.

## Proposed sequence

1. Characterize public callable behavior: ordered cases, composed predicates,
   defaults, structural captures, generic controllers, unsupported relationships,
   finite arities, published stubs, overlays, and verification obligations.
2. Separate language evaluation from candidate enumeration and emission policy.
   Identify which shared interfaces already apply and which contracts are missing.
3. Adapt callable inputs to shared expressions while preserving authored alias
   information, generic identity, and any meaningful default distinctions.
4. Cut over one supported callable family at a time, retaining its generated
   interface and verification behavior. Record intended corrections explicitly.
5. Delete superseded semantic helpers after migrating all their consumers, and
   protect the ownership boundary with focused architecture tests.

Each implementation slice must pass focused checks and full `make check`.

## Promotion criteria

The public Pydantic integration now exercises shared semantics for resolved
transformations and deferred Input selection; that prerequisite is complete.
Promotion still requires an explicit behavior matrix and an agreed seam between
semantic decisions and finite specialization.

Completion means callable language evaluation uses shared semantics without
duplicating case selection or predicate rules, while compiler-specific
representation policies remain explicit and their regression tests pass.
