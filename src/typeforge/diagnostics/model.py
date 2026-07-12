from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ProblemKind(StrEnum):
    NO_MATCHING_OVERLOAD = "no_matching_overload"


class AuthoredParameterKind(StrEnum):
    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"


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
class AuthoredParameter:
    name: str
    kind: AuthoredParameterKind
    annotation: str | None
    has_default: bool


@dataclass(frozen=True, slots=True)
class AuthoredCallable:
    qualified_name: tuple[str, ...]
    parameters: tuple[AuthoredParameter, ...]
    return_annotation: str | None

    @property
    def display_name(self) -> str:
        return ".".join(self.qualified_name)


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
