"""Construct reusable, immutable typing templates during an ordinary import."""

from inspect import iscoroutinefunction, isgeneratorfunction, signature
from types import CellType, FunctionType, GenericAlias
from typing import (
    Annotated,
    Any,
    Literal,
    Never,
    TypeAliasType,
    TypeVar,
    get_args,
    get_origin,
)

from typeforge._capture import Capture, CaptureSymbol
from typeforge._field import UNCHANGED, FieldReplacementTemplate, FieldTemplate
from typeforge._record import (
    FieldNameTemplate,
    FieldSymbol,
    FieldTypeTemplate,
    SymbolicField,
)


class TypeFunctionConstructionError(TypeError):
    """The construction did not produce a supported reusable type template."""


class SymbolicTypeParameter(GenericAlias):
    """An immutable typing bridge that retains the parameter's original identity."""

    def __bool__(self) -> bool:
        raise TypeFunctionConstructionError(
            "symbolic type truthiness is unsupported; use Map for type selection"
        )


def type_function(function: FunctionType) -> TypeAliasType:
    """Execute a parameterless construction once; specialization uses its alias."""
    if (
        iscoroutinefunction(function)
        or isgeneratorfunction(function)
        or signature(function).parameters
    ):
        raise TypeFunctionConstructionError(
            "type_function requires a synchronous function without value parameters"
        )

    parameters = tuple(
        parameter
        for parameter in function.__type_params__
        if isinstance(parameter, TypeVar)
    )
    if len(parameters) != len(function.__type_params__):
        raise TypeFunctionConstructionError(
            "type_function requires ordinary type parameters"
        )

    if any(
        parameter.__bound__ is not None
        or parameter.__constraints__
        or parameter.has_default()
        for parameter in parameters
    ):
        raise TypeFunctionConstructionError(
            "type_function currently requires unconstrained parameters without defaults"
        )

    constructor = _symbolic_constructor(function, parameters)
    template: object = constructor()
    _validate_template(template, parameters)
    # TypeAliasType derives __module__ from its caller's globals. Run only our
    # alias factory code in that namespace to retain authored module identity.
    factory = FunctionType(_named_alias.__code__, function.__globals__)
    alias: TypeAliasType = factory(
        function.__name__, template, parameters, TypeAliasType
    )
    return alias


def _named_alias(
    name: str,
    template: object,
    parameters: tuple[TypeVar, ...],
    constructor: type[TypeAliasType],
) -> TypeAliasType:
    # Runtime factories use dynamic names rather than source alias assignments.
    return constructor(  # pyright: ignore[reportGeneralTypeIssues]
        name, template, type_params=parameters
    )


def _symbolic_constructor(
    function: FunctionType, parameters: tuple[TypeVar, ...]
) -> FunctionType:
    if function.__closure__ is None:
        return function

    cells: list[CellType] = []
    parameter_names = {parameter.__name__ for parameter in parameters}
    for name, cell in zip(
        function.__code__.co_freevars, function.__closure__, strict=True
    ):
        if name not in parameter_names:
            cells.append(cell)
            continue

        value: object = cell.cell_contents
        if isinstance(value, TypeVar) and value in parameters:
            cells.append(
                CellType(SymbolicTypeParameter(SymbolicTypeParameter, (value,)))
            )
        else:
            cells.append(cell)

    return FunctionType(
        function.__code__,
        function.__globals__,
        function.__name__,
        function.__defaults__,
        tuple(cells),
    )


def _validate_template(value: object, parameters: tuple[TypeVar, ...]) -> None:
    if value is None or value is Any or value is Never:
        return

    if isinstance(value, TypeVar):
        if value not in parameters:
            raise TypeFunctionConstructionError(
                f"unbound type parameter in type_function template: {value.__name__}"
            )

        return

    if isinstance(value, type | TypeAliasType):
        return

    origin = get_origin(value)
    if origin is FieldReplacementTemplate:
        arguments = get_args(value)
        if len(arguments) != 5 or not all(
            argument is UNCHANGED or isinstance(argument, bool)
            for argument in arguments[3:]
        ):
            raise TypeFunctionConstructionError("invalid field replacement template")

        _validate_template(arguments[0], parameters)
        if arguments[1] is not UNCHANGED:
            _validate_template(arguments[1], parameters)

        if arguments[2] is not UNCHANGED:
            _validate_template(arguments[2], parameters)

        return

    if origin is FieldTemplate:
        arguments = get_args(value)
        if len(arguments) != 4 or not all(
            isinstance(argument, bool) for argument in arguments[2:]
        ):
            raise TypeFunctionConstructionError("invalid Field template")

        _validate_template(arguments[0], parameters)
        _validate_template(arguments[1], parameters)
        return

    if origin in (SymbolicField, FieldNameTemplate, FieldTypeTemplate):
        arguments = get_args(value)
        if len(arguments) != 1 or not isinstance(arguments[0], FieldSymbol):
            raise TypeFunctionConstructionError("invalid symbolic field binding")

        return

    if origin is Capture:
        arguments = get_args(value)
        if len(arguments) != 1 or not isinstance(arguments[0], CaptureSymbol):
            raise TypeFunctionConstructionError("invalid capture declaration")

        return

    if origin is None:
        raise TypeFunctionConstructionError(
            f"type_function must return a type template; received {value!r}"
        )

    if origin is Literal:
        return

    arguments = get_args(value)[:1] if origin is Annotated else get_args(value)
    for argument in arguments:
        if argument is not Ellipsis:
            _validate_template(argument, parameters)
