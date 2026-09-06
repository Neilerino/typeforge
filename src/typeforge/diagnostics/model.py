from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from typeforge.compiler.pipeline import AuthoredCallable


class ProblemKind(StrEnum):
    NO_MATCHING_OVERLOAD = "no_matching_overload"


@dataclass(frozen=True, slots=True)
class CheckerDetail:
    checker: str
    code: str | None
    message: str


@dataclass(frozen=True, slots=True)
class TypeProblem:
    kind: ProblemKind
    callable_name: str
    received: tuple[str, ...]
    checker_detail: CheckerDetail


@dataclass(frozen=True, slots=True)
class Explanation:
    title: str
    received: tuple[str, ...]
    expected: tuple[str, ...]
    reasons: tuple[str, ...]
    checker_detail: CheckerDetail


class ExplanationRule(Protocol):
    def __call__(
        self,
        problem: TypeProblem,
        callables: tuple[AuthoredCallable, ...],
    ) -> Explanation | None: ...
