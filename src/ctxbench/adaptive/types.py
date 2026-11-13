from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Mapping

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


@dataclass(frozen=True)
class RequestFeatures:
    """Request features used by the current workflow; identities stay on the request."""
    sequence_index: int
    context_bytes: int

    def __post_init__(self) -> None:
        if (type(self.sequence_index) is not int or type(self.context_bytes) is not int
                or self.sequence_index < 1 or self.context_bytes < 0):
            raise ValueError("invalid request features")


@dataclass(frozen=True)
class ContextFit:
    input_tokens: int
    output_reservation: int
    context_limit: int
    provenance: Provenance

    def __post_init__(self) -> None:
        if (any(type(v) is not int for v in (self.input_tokens, self.output_reservation, self.context_limit))
                or min(self.input_tokens, self.output_reservation, self.context_limit) < 0):
            raise ValueError("context budget must be nonnegative")
        if self.provenance not in (Provenance.DERIVED, Provenance.ESTIMATED):
            raise ValueError("context fit requires tokenizer-derived or estimated assessment")

    @property
    def fits(self) -> bool:
        return self.input_tokens + self.output_reservation <= self.context_limit


@dataclass(frozen=True)
class Candidate:
    configuration_id: str
    executable: bool
    context_fit: ContextFit

    @property
    def eligibility_reasons(self) -> tuple[str, ...]:
        return tuple(reason for failed, reason in (
            (not self.executable, "not_executable"),
            (not self.context_fit.fits, "context_capacity_exceeded")) if failed)

    @property
    def eligible(self) -> bool:
        return not self.eligibility_reasons


def validate_candidates(candidates: tuple[Candidate, ...]) -> None:
    ids = [c.configuration_id for c in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate IDs must be unique")


@dataclass(frozen=True)
class Estimate:
    value: float | None
    provenance: Provenance
    observation_count: int
    source_provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        validate_metric(self.value, self.provenance)
        if type(self.observation_count) is not int or self.observation_count < 0:
            raise ValueError("observation_count must be nonnegative")


@dataclass(frozen=True)
class PerformanceEstimate:
    latency_ms: Estimate
    total_tokens: Estimate


@dataclass(frozen=True)
class TokenUsage:
    value: int | None
    provenance: Provenance

    def __post_init__(self) -> None:
        validate_metric(self.value, self.provenance)


@dataclass(frozen=True)
class Observation:
    configuration_id: str
    status: str
    end_to_end_duration_ms: float | None
    tokens: TokenUsage
    duration_provenance: Provenance = Provenance.MEASURED

    def __post_init__(self) -> None:
        if not self.configuration_id:
            raise ValueError("observation requires a configuration")
        validate_metric(self.end_to_end_duration_ms, self.duration_provenance)

    @property
    def valid(self) -> bool:
        return self.status == "success"


def unavailable_estimate() -> PerformanceEstimate:
    missing = Estimate(None, Provenance.UNAVAILABLE, 0)
    return PerformanceEstimate(missing, missing)


@dataclass(frozen=True)
class Decision:
    sequence_index: int
    features: RequestFeatures
    eligible_candidates: tuple[str, ...]
    estimates: Mapping[str, PerformanceEstimate]
    selected_configuration: str | None
    reason: str
    probe: bool
    cooldown_active: bool
    normal_configuration: str | None = None
    objective_attainment: str = "unknown"
    candidates: tuple[Candidate, ...] = ()
