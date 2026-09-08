"""Modeled integration issues, before Pydantic exception presentation."""

from dataclasses import dataclass

from typeforge.pydantic._display import format_annotation


@dataclass(frozen=True, slots=True)
class SchemaIssue(Exception):
    code: str
    phase: str
    expression: object
    message: str

    def render(self) -> str:
        return (
            f"Typeforge schema {self.phase} failed [{self.code}] "
            f"for {format_annotation(self.expression)}: {self.message}"
        )


@dataclass(frozen=True, slots=True)
class UnresolvedAnnotationIssue(SchemaIssue):
    name: str


@dataclass(frozen=True, slots=True)
class UnsupportedRecordIssue(SchemaIssue):
    uses_generic_fallback: bool
    subject: object

    def render(self) -> str:
        subject = format_annotation(self.subject)
        return f"{SchemaIssue.render(self)} (subject: {subject})"


@dataclass(frozen=True, slots=True)
class MapNoMatchIssue(SchemaIssue):
    uses_generic_fallback: bool
    subject: object

    def render(self) -> str:
        subject = format_annotation(self.subject)
        return f"{SchemaIssue.render(self)} (subject: {subject})"
