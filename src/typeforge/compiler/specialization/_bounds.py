"""Project unresolved relationships to sound ordinary checker output bounds."""

from dataclasses import replace

from typeforge.compiler.stub_ir import (
    CaptureType,
    MapType,
    StubTypeExpression,
    TypeApplication,
    TypeName,
    TypeRewriteObserver,
    TypeVariable,
    UnionExpression,
    rewrite_type_children,
    union_types,
)
from typeforge.semantics import GenericFamily, generic_family


def checker_type_bound(
    expression: StubTypeExpression,
    *,
    invariant: bool = False,
    type_parameters: frozenset[str] | None = None,
    on_rewrite: TypeRewriteObserver | None = None,
) -> StubTypeExpression:
    match expression:
        case MapType(cases=cases, default=default):
            outputs = tuple(case.output_type for case in cases)
            if default is not None:
                outputs += (default,)

            result: StubTypeExpression = checker_type_bound(
                union_types(outputs),
                invariant=invariant,
                type_parameters=type_parameters,
                on_rewrite=on_rewrite,
            )
        case UnionExpression(members):
            result = union_types(
                tuple(
                    checker_type_bound(
                        member,
                        invariant=invariant,
                        type_parameters=type_parameters,
                        on_rewrite=on_rewrite,
                    )
                    for member in members
                )
            )
        case TypeVariable(name) if (
            type_parameters is not None and name not in type_parameters
        ):
            result = TypeName("Any" if invariant else "object")
        case CaptureType():
            result = TypeName("Any" if invariant else "object")
        case TypeApplication(constructor, arguments):
            result = replace(
                expression,
                arguments=tuple(
                    checker_type_bound(
                        argument,
                        invariant=invariant or _invariant_argument(constructor, index),
                        type_parameters=type_parameters,
                        on_rewrite=on_rewrite,
                    )
                    for index, argument in enumerate(arguments)
                ),
            )
        case _:
            result = rewrite_type_children(
                expression,
                lambda child: checker_type_bound(
                    child,
                    invariant=invariant,
                    type_parameters=type_parameters,
                    on_rewrite=on_rewrite,
                ),
            )

    if on_rewrite is not None:
        on_rewrite(expression, result)

    return result


def _invariant_argument(constructor: StubTypeExpression, index: int) -> bool:
    if not isinstance(constructor, TypeName):
        return True

    if constructor.name in {"Annotated", "typing.Annotated"}:
        return index != 0

    match generic_family(constructor.name):
        case GenericFamily.LIST | GenericFamily.SET | GenericFamily.DICT:
            return True
        case GenericFamily.MAPPING:
            return index == 0
        case GenericFamily.TUPLE | GenericFamily.FROZENSET | GenericFamily.SEQUENCE:
            return False
        case None:
            # Native typing cannot spell an existential invariant argument.
            # Any is the truthful gradual bound at this publication boundary.
            return True
