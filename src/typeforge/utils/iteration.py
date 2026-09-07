from collections.abc import Callable, Iterable


def tmap[T, R](f: Callable[[T], R], iterable: Iterable[T]) -> tuple[R, ...]:
    """
    type hinted util for returning immutable (tuple) result from a map call
    """
    return tuple(map(f, iterable))
