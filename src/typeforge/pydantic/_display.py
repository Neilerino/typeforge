"""Present normalized annotations using the public authoring syntax."""

from collections.abc import Callable
from types import NoneType
from typing import Annotated, Literal, Union, cast, get_args, get_origin

from typeforge._markers import Case, Default, Equal, Map


def format_annotation(value: object) -> str:
    """Traverse typing arguments without evaluating alias bodies or metadata."""
    origin = get_origin(value)
    arguments: tuple[object, ...] = get_args(value)
    if origin is Map and arguments:
        subject, *entries = arguments
        parts = [format_annotation(subject)]
        parts.extend(_format_branch(entry, subject=subject) for entry in entries)
        return f"Map[{', '.join(parts)}]"

    if origin is Literal:
        return f"Literal[{', '.join(repr(item) for item in arguments)}]"

    if origin is Annotated:
        annotation, *metadata = arguments
        parts = [format_annotation(annotation), *(repr(item) for item in metadata)]
        return f"Annotated[{', '.join(parts)}]"

    if origin is Union:
        return " | ".join(format_annotation(item) for item in arguments)

    if origin is Callable and len(arguments) == 2 and isinstance(arguments[0], list):
        # Typing introspection erases the element type of Callable parameter lists.
        parameters = cast(list[object], arguments[0])
        parameter_text = ", ".join(format_annotation(item) for item in parameters)
        result = format_annotation(arguments[1])
        return f"collections.abc.Callable[[{parameter_text}], {result}]"

    if origin is not None:
        constructor = format_annotation(origin)
        return (
            f"{constructor}[{', '.join(format_annotation(arg) for arg in arguments)}]"
        )

    if value is None or value is NoneType:
        return "None"

    if value is Ellipsis:
        return "..."

    if isinstance(value, type):
        if value.__module__ == "builtins":
            return value.__qualname__

        return f"{value.__module__}.{value.__qualname__}"

    return repr(value)


def _format_branch(value: object, *, subject: object) -> str:
    origin = get_origin(value)
    arguments: tuple[object, ...] = get_args(value)
    if origin is Case and len(arguments) == 2:
        selector, output = arguments
        operands: tuple[object, ...] = get_args(selector)
        if (
            get_origin(selector) is Equal
            and len(operands) == 2
            and operands[0] is subject
        ):
            return f"Is[{format_annotation(operands[1])}]: {format_annotation(output)}"

        return f"{format_annotation(selector)}: {format_annotation(output)}"

    if origin is Default and len(arguments) == 1:
        return f"...: {format_annotation(arguments[0])}"

    return format_annotation(value)
