"""Typed failures returned by shared semantic evaluation."""

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar


class SemanticIssueCode(StrEnum):
    ADAPTER = "adapter"
    DUPLICATE_FIELD = "duplicate_field"
    EXPECTED_CONDITION = "expected_condition"
    EXPECTED_FIELD = "expected_field"
    EXPECTED_FIELD_NAME = "expected_field_name"
    EXPECTED_RECORD = "expected_record"
    EXPECTED_TYPE = "expected_type"
    NO_MATCH = "no_match"
    UNBOUND_INPUT = "unbound_input"
    UNBOUND_CAPTURE = "unbound_capture"
    UNBOUND_FIELD = "unbound_field"
    UNRESOLVED_CAPTURE = "unresolved_capture"
    UNSUPPORTED_EXPRESSION = "unsupported_expression"


@dataclass(frozen=True, slots=True)
class SemanticIssue(Exception):
    """An expected failure crossing the semantic evaluation seam."""

    message: str

    code: ClassVar[SemanticIssueCode]


class SemanticAdapterError(SemanticIssue):
    code = SemanticIssueCode.ADAPTER


class DuplicateFieldSemanticError(SemanticIssue):
    code = SemanticIssueCode.DUPLICATE_FIELD


class ExpectedConditionSemanticError(SemanticIssue):
    code = SemanticIssueCode.EXPECTED_CONDITION


class ExpectedFieldSemanticError(SemanticIssue):
    code = SemanticIssueCode.EXPECTED_FIELD


class ExpectedFieldNameSemanticError(SemanticIssue):
    code = SemanticIssueCode.EXPECTED_FIELD_NAME


class ExpectedRecordSemanticError(SemanticIssue):
    code = SemanticIssueCode.EXPECTED_RECORD


class ExpectedTypeSemanticError(SemanticIssue):
    code = SemanticIssueCode.EXPECTED_TYPE


class NoMatchSemanticError(SemanticIssue):
    code = SemanticIssueCode.NO_MATCH


class UnboundInputSemanticError(SemanticIssue):
    code = SemanticIssueCode.UNBOUND_INPUT


class UnboundCaptureSemanticError(SemanticIssue):
    code = SemanticIssueCode.UNBOUND_CAPTURE


class UnboundFieldSemanticError(SemanticIssue):
    code = SemanticIssueCode.UNBOUND_FIELD


class UnresolvedCaptureSemanticError(SemanticIssue):
    code = SemanticIssueCode.UNRESOLVED_CAPTURE


class UnsupportedExpressionSemanticError(SemanticIssue):
    code = SemanticIssueCode.UNSUPPORTED_EXPRESSION
