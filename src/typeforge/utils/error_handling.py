from collections.abc import Callable
from functools import wraps
from typing import Protocol, cast

from returns.interfaces.unwrappable import Unwrappable
from returns.primitives.exceptions import UnwrapFailedError
from returns.result import Failure, Result, safe


class _FailedUnwrap(Protocol):
    # returns leaves the container's generic arguments unspecified on the exception.
    halted_container: Unwrappable[object, object]


def safe_result[**P, T, E](
    *, errors: tuple[type[E], ...]
) -> Callable[[Callable[P, T]], Callable[P, Result[T, E]]]:
    """Convert declared errors, raised or unwrapped, at a Result boundary.

    Error values may be exceptions or plain data. Unexpected exceptions and
    unwraps of undeclared failures or non-Result containers propagate unchanged.
    """
    exceptions = (
        *(error for error in errors if issubclass(error, Exception)),
        UnwrapFailedError,
    )

    def decorate(function: Callable[P, T]) -> Callable[P, Result[T, E]]:
        call_safely: Callable[P, Result[T, Exception]] = safe(exceptions=exceptions)(
            function
        )

        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> Result[T, E]:
            return call_safely(*args, **kwargs).alt(
                lambda error: _declared_error(error, errors)
            )

        return wrapped

    return decorate


def _declared_error[E](error: Exception, errors: tuple[type[E], ...]) -> E:
    if isinstance(error, UnwrapFailedError):
        container = cast(_FailedUnwrap, error).halted_container
        if isinstance(container, Failure):
            failure: object = container.failure()
            if isinstance(failure, errors):
                return failure

        raise error

    if isinstance(error, errors):
        return error

    raise error


def ok[T, E: Exception](result: Result[T, E]) -> T:
    if isinstance(result, Failure):
        raise result.failure()

    return result.unwrap()
