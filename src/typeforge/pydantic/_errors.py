"""Modeled integration issues, before Pydantic exception presentation."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SchemaIssue(Exception):
    code: str
    phase: str
    expression: object
    message: str

    def render(self) -> str:
        return (
            f"Typeforge schema {self.phase} failed [{self.code}] "
            f"for {self.expression!r}: {self.message}"
        )


@dataclass(frozen=True, slots=True)
class MapNoMatchIssue(SchemaIssue):
    uses_generic_fallback: bool
    subject: object

    def render(self) -> str:
        return f"{SchemaIssue.render(self)} (subject: {self.subject!r})"
