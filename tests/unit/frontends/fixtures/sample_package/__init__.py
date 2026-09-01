from typing import TypedDict, overload

from typeforge import Collect, Each

__all__ = ["Parser", "User", "combine", "parse"]


class User(TypedDict):
    name: str
    age: int


class Parser[T]:
    @property
    def value(self) -> T:
        raise NotImplementedError


@overload
def parse(value: int) -> Parser[int]: ...


@overload
def parse(value: str) -> Parser[str]: ...


def parse(value: int | str) -> Parser[int] | Parser[str]:
    raise NotImplementedError


def combine[T](*parsers: Each[Parser[T]]) -> Parser[Collect[T]]:
    raise NotImplementedError


def _private_function() -> None:
    raise NotImplementedError
