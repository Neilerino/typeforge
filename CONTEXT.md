# Typeforge

Typeforge describes authored type relationships and projects their meaning into
standard Python typing interfaces.

## Language

**Runtime Input**:
The input whose type becomes available when a value is supplied for validation.
It is distinct from an unresolved static type parameter.

**Type symbol**:
The identity of an authored type parameter within its declaring scope. Two uses
of that parameter share a symbol; equally named parameters in different scopes
do not.

**Unresolved static type**:
A type whose concrete identity still depends on a type symbol, including a
parameterized type with unresolved positions. Known positions retain their meaning.

**Indeterminate result**:
A result whose selection cannot yet be decided from the available static type
information. Its possible alternatives are distinct from a definite union type.

**Possible output type**:
The type encompassing the outputs that a Map may produce. A no-match path
contributes no output type.

**Deferred Map**:
An ordered Map whose case selection awaits Runtime Input. Its cases, default,
and available bindings remain meaningful while selection is deferred.
