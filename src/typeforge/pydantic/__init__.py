try:
    from typeforge.pydantic._schema import Input, Schema
except ModuleNotFoundError as error:
    if error.name not in {"pydantic", "pydantic_core"}:
        raise
    raise ModuleNotFoundError(
        "Typeforge's Pydantic integration requires the optional dependency; "
        "install it with `pip install 'typeforge[pydantic]'`"
    ) from error

__all__ = ["Input", "Schema"]
