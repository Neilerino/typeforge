import typeforge as tf
from typeforge import Collect as Gather
from typeforge import Each


class Parser[T]:
    pass


def combine[T](
    first: int,
    /,
    *parsers: Each[Parser[T]],
    strict: bool = False,
    **options: str,
) -> Parser[Gather[T]]:
    raise NotImplementedError


class Factory:
    async def create[T](self, *values: tf.Each[T]) -> tf.Collect[T]:
        raise NotImplementedError


def ordinary(value: int) -> str:
    return str(value)
