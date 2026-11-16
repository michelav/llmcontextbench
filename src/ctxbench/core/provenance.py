"""Shared metric provenance and value contracts."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class Provenance(StrEnum):
    REPORTED = "reported"
    MEASURED = "measured"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


def validate_metric(value: float | None, provenance: Provenance) -> None:
    if (value is None) != (provenance == Provenance.UNAVAILABLE):
        raise ValueError("missing values require unavailable provenance and vice versa")
    if value is not None and (not isfinite(value) or value < 0):
        raise ValueError("metrics must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    value: int | None
    provenance: Provenance

    def __post_init__(self) -> None:
        validate_metric(self.value, self.provenance)


__all__ = ["Provenance", "TokenUsage", "validate_metric"]
