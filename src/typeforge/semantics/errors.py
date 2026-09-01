"""Typed failures returned by shared semantic evaluation."""

from dataclasses import dataclass
from enum import StrEnum


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
    UNBOUND_KEY = "unbound_key"
    UNBOUND_VALUE = "unbound_value"
    UNSUPPORTED_EXPRESSION = "unsupported_expression"


@dataclass(frozen=True, slots=True)
class SemanticIssue(Exception):
    """An expected failure crossing the semantic evaluation seam."""

    code: SemanticIssueCode
    message: str
