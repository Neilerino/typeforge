from typing import assert_type

from typeforge import Collect, Each


class Parser[T]:
    pass


def combine[T](*parsers: Each[Parser[T]]) -> Parser[Collect[T]]:
    raise NotImplementedError


integer_parser = Parser[int]()
string_parser = Parser[str]()

assert_type(combine(integer_parser), Parser[tuple[int, ...]])
assert_type(
    combine(integer_parser, string_parser),
    Parser[tuple[object, ...]],
)
