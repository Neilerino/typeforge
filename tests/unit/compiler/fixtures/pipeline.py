from external import Parser

from typeforge import Collect, Each


def identity[T](value: T) -> T:
    return value


def combine[T](*parsers: Each[Parser[T]]) -> Parser[Collect[T]]:
    raise NotImplementedError
