"""Modeled failures produced while rendering stub IR."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmissionError:
    message: str
