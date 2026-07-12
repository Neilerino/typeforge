from typing import Never

type Each[T] = T
type Collect[T] = tuple[T, ...]

type If[Condition, Then, Else] = Then | Else
type Assignable[Source, Target] = bool
type Equal[Left, Right] = bool
type All[*Conditions] = bool
type Any[*Conditions] = bool
type Not[Condition] = bool

type Case[Input, Output] = Output
type Default[Output] = Output
type Map[Subject, *Cases] = object

type MapFields[Record, Transform] = object
type Field[Name, Type] = Type
type OptionalField[Name, Type] = Type
type ReadonlyField[Name, Type] = Type
type Drop = Never
type Key = str
type Value = object
