# Typeforge Project Goal

## Mission

Typeforge lets Python developers express richer type relationships beside their implementation code and compiles them into portable `.pyi` interfaces for existing type checkers.

It is not a type checker. It is an authoring layer and compiler targeting the typing constructs that mypy, Pyright, Pyrefly, ty, and future checkers already understand.

## Why It Exists

Python cannot ergonomically express several useful type relationships, including:

* mapping over heterogeneous variadic arguments;
* extracting a type from a generic wrapper;
* deriving record variants such as partial, selected, or omitted fields;
* correlating literal inputs with return types;
* transforming callable signatures.

Some of these ideas are being explored by proposals such as draft PEP 827. Those proposals validate the demand, but may change, take years to gain broad checker support, or never be accepted. Typeforge should be useful independently of standardization. If suitable features are standardized later, it can emit them when supported and provide a compatibility path for older environments.

## Design Constraints

* Source remains valid Python. No new language, interpreter, transpiled runtime, or checker plugin.
* Type intent lives near the implementation.
* Runtime helpers have reasonable fallback types; importing them never generates code or changes program semantics.
* The compiler parses source without importing or executing it.
* Generated output uses standard `.pyi` constructs and is deterministic from library source and configuration.
* Consumers of published stubs do not run or configure Typeforge. A library may carry the inert marker package as a small transitive dependency.
* Diagnostics point to authored source, not generated files.

A `.pyi` file replaces the corresponding implementation as the module interface seen by a checker. Typeforge must therefore generate a complete interface for every module it shadows, not a partial patch.

## Expressiveness Boundary

Typeforge can handle three kinds of relationship:

1. **Standard generic relationships** are emitted directly with constructs such as `TypeVar`, `TypeVarTuple`, `ParamSpec`, and overloads.
2. **Finite transformations** over known models, fields, literals, or arities are compiled into concrete aliases, structural types, or overload sets.
3. **Open-ended downstream transformations** may not be representable in today's `.pyi` language. Typeforge must use a documented finite frontier, require project-local specialization, provide a less precise fallback, or report that the relationship is not portably lowerable.

Finite specialization must never be presented as an open-ended generic capability.

## Operating Modes

### Library mode

Library authors generate deterministic stubs to publish with their package. Unknown downstream consumers are supported through an explicit policy such as a configured arity frontier. Consumer call sites never affect published output.

### Project mode

Applications and monorepos use ephemeral source overlays for implementation-file precision or generate local stubs. A checker adapter receives transformed source under its original identity and maps diagnostics back to authored locations. Typeforge may inspect local schemas, typing tests, literals, and call sites to discover useful specializations. Project-local output is not publishable by default.

## Authoring Syntax Direction

Typeforge should use small, composable generic aliases that remain inert at runtime and degrade to valid, less precise annotations without generated stubs. The names remain provisional until tested with mypy and Pyright.

Variadic capture and collection:

```python
def combine[T](
    *parsers: Each[Parser[T]],
) -> Parser[Collect[T]]: ...
```

Conditional types:

```python
If[Assignable[T, str], str, bytes]
```

Finite type maps:

```python
Map[
    T,
    Case[int, float],
    Case[bytes, str],
    Default[T],
]
```

Inside a structural `Case`, `Value` captures one nested generic argument and can be referenced by the output:

```python
type QueryResult[T] = Map[
    T,
    Case[Option[Value], Value | None],
    Default[T],
]
```

Field maps bind `Key` and `Value` for each field in a known record shape:

```python
type JsonSafe[T] = MapFields[
    T,
    Field[
        Key,
        Map[
            Value,
            Case[datetime, str],
            Case[UUID, str],
            Default[Value],
        ],
    ],
]
```

`Field`, `OptionalField`, `ReadonlyField`, and `Drop` describe the output field. `If`, `Equal`, `Assignable`, `All`, `Any`, and `Not` compose conditions. A missing `Default` in `Map` means `Never`.

The first field-mapping implementation should support named `TypedDict`s and, in project mode, contextually typed dictionary literals. Plain `dict` variables may already have lost the relationship between individual keys and value types and cannot always be recovered.

Other record families require explicit adapters. Dataclasses, protocols, ordinary classes, attrs classes, and validation models have different construction, inheritance, mutation, and runtime semantics and must not be treated as interchangeable merely because they have annotations.

These helpers must not wrap functions, methods, classes, or values. They exist only as source-level typing markers; application call paths incur no Typeforge overhead.

## MVP

The first release proves one high-value feature: heterogeneous variadic mapping with structural capture.

```text
query(Position, Velocity)
  -> Query[tuple[Position, Velocity]]

combine(Parser[int], Parser[str])
  -> Parser[tuple[int, str]]
```

Python can preserve a `TypeVarTuple`, but cannot generally transform each member by extracting a nested type. The MVP lowers this relationship into generated overloads for a configured arity range.

The MVP includes:

1. One readable authoring syntax.
2. An inert helper package with fallback annotations.
3. A Python-based parser for enriched declarations in one module.
4. Complete stub generation for a small subset of functions, classes, imports, and aliases.
5. Variadic wrapper extraction lowered to overloads.
6. Source-based diagnostics.
7. Golden-file tests and consumer tests with mypy and Pyright.

It must answer:

1. Is the authoring syntax clearer and easier to maintain than handwritten overloads?
2. Can multiple checkers consume the generated interface consistently?

## Compiler Shape

```text
Python source with Typeforge declarations
    -> parser and limited symbol resolution
    -> Typeforge semantic IR
    -> standard typing IR
    -> complete .pyi modules or ephemeral checker overlays
```

The semantic IR represents relationships such as capture, mapping, and finite specialization. The standard typing IR contains only portable stub constructs.

The first implementation should use Python's parsing facilities to optimize for iteration on syntax and semantics. Rust should be considered only if profiling later identifies a meaningful performance or distribution constraint.

## Deferred Work

After the MVP:

* project-mode specialization, watch mode, and incremental caching;
* additional checker adapters and normalized interactive features;
* static contract verification and opt-in runtime verification;
* callable transformations beyond finite variadic mapping;
* filtering, projection, remapping, and adapters for additional record families.

Record transformations must define separate semantics for each supported family. `TypedDict`, dataclasses, protocols, ordinary classes, attrs classes, and validation models are not one interchangeable abstraction.

Any contract verification that imports or executes user code, including verification through tools such as `stubtest`, must be explicit and opt-in.

## Success Criteria

Typeforge succeeds if it lets library authors publish materially better types without requiring consumer opt-in, gives opted-in projects useful additional precision, and works consistently across existing type checkers without becoming one itself.
