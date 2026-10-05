# Type selector precedents

Research date: 2026-09-09. Primary-source comparison for the
[open Map selection decisions](map-selection-decisions.md), especially public
Assignable/Is and generic implementation verification. Recommendations below
are discussion inputs, not approved semantics or implementation instructions.
Examples are illustrative applications of the cited rules; foreign compilers
were not run for this note.

## TypeScript: compatibility and distribution are separate choices

Conditional types use assignment compatibility: `T extends U ? A : B` selects
A when T is assignable to U. A naked generic parameter in the checked position
distributes over union members; tuple wrapping disables that distribution.
Wrapping does not change compatibility into exact equality.
[Conditional types](https://www.typescriptlang.org/docs/handbook/2/conditional-types.html)

```typescript
type Distributed<T> = T extends number ? string : boolean;
type Whole<T> = [T] extends [number] ? string : boolean;

type A = Distributed<number | string>; // string | boolean
type B = Whole<number | string>;       // boolean
type C = Whole<1>;                     // string: compatible, not exactly number
```

Its `infer` syntax also captures structural components, as in
`T extends Array<infer Item> ? Item : T`. This is precedent for extracting an
element type, not inspecting collection values at runtime. The handbook's
generic conditional-return example deliberately has an unimplemented body;
that example does not establish arbitrary runtime-guard verification.
[Inference and function example](https://www.typescriptlang.org/docs/handbook/2/conditional-types.html)

Design inference: our memberwise/whole-subject distinction has clear precedent,
but bundling whole-subject behavior into a different comparison helper is a
separate Typeforge choice.

## Scala: type matching must account for overlapping possibilities

Scala match types support ordered cases and structural captures:
[Match types](https://docs.scala-lang.org/scala3/reference/new-types/match-types.html)

```scala
type Element[X] = X match
  case Array[t] => t
  case String   => Char
```

Reduction selects a case when the subject is a subtype of its pattern. If that
fails, it skips the case only when it can prove the types disjoint. Otherwise
the match remains unreduced. Thus a whole subject `Int | String` overlaps an
`Int` case: failure of the subtype check alone does not justify selecting a
fallback. This differs from a Boolean whole-type compatibility test.
[Reduction rules](https://docs.scala-lang.org/scala3/reference/new-types/match-types.html#match-type-reduction)

Scala can check corresponding value matches against match-type returns under
restrictions: no guards, compatible scrutinee type, matching case counts, and
equivalent typed patterns. Even then, checking a case body does not constrain
the original generic argument to that case's pattern.
[Dependent typing](https://docs.scala-lang.org/scala3/reference/new-types/match-types.html#dependent-typing)

The implemented SIP-56 formalizes supported patterns and reduction; it records
the complexity of preserving useful abstract captures while tightening the
specification.
[SIP-56](https://docs.scala-lang.org/sips/match-types-spec.html)

Design inference: Scala directly addresses our guard example. A runtime value
can enter the integer branch while its original static subject still includes
strings. An unreduced type, a safe output bound, and a selected fallback are
different outcomes and should not be conflated.

## C++: distinct relations, with branching on static types

C++ exposes multiple named relations rather than one universal type match:

| Relation | What it establishes |
| --- | --- |
| `std::same_as<T, U>` | The same type, through `is_same_v`. [Working draft](https://eel.is/c++draft/concept.same) |
| `std::derived_from<T, U>` | The same class or public, unambiguous derivation. [Working draft](https://eel.is/c++draft/concept.derived) |
| `std::convertible_to<T, U>` | Implicit and explicit conversions satisfying its semantic requirements. [Working draft](https://eel.is/c++draft/concept.convertible) |

A template can use its static type relation as a compile-time branch condition:

```cpp
template<class T>
auto encode(T value) {
    if constexpr (std::same_as<T, int>)
        return std::to_string(value);
    else
        return false;
}
```

With the necessary headers, this illustrates selection from T itself.
`if constexpr` requires a constant condition; once resolved during template
instantiation, the discarded branch is not instantiated. This is different
from testing the current value with an ordinary runtime guard.
[Working draft: constexpr if](https://eel.is/c++draft/stmt.if)

Design inference: exact type selection is useful precedent, but its safe
implementation here relies on access to the static template argument.
It is not evidence that Python's `isinstance` can recover an inferred T.

## C#: naming warning for Is

C# `value is Base` checks runtime compatibility, including derived instances;
exact runtime type comparison instead uses `value.GetType() == typeof(Base)`.
[Microsoft reference](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/operators/type-testing-and-cast)

Design inference: the name Is does not universally suggest exact whole-type
equivalence. Its proposed Typeforge meaning would need explicit teaching.

## Implications to discuss

The comparison suggests three independent questions:

1. **Relation:** exact equivalence, subtyping, or assignment compatibility?
2. **Scope:** compare the whole subject, or map each union member?
3. **Phase:** inspect a static annotation/type parameter, or a runtime value?

Our proposed bare selectors and Is change both relation/scope presentation,
while callable guards introduce the phase distinction. Removing Assignable
would reduce public vocabulary but would not settle the whole-subject guard
problem. Keeping compatibility selection would have substantial precedent,
but that does not establish a required near-term Typeforge use case.

Recommendation for discussion: settle these axes and implementation-verification
expectations before deciding the helper names. Preserve already agreed examples
as explicit constraints; any revision needs the user's agreement. In particular,
do not silently change exact bare matching to Scala-style subtype matching or
change whole-subject Assignable into memberwise matching.
