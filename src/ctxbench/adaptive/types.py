from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class SizeBin(StrEnum):
    SMALL = "small"
    LARGE = "large"


class Provenance(StrEnum):
    REPORTED = "reported"
    MEASURED = "measured"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RequestFeatures:
    """Policy-visible request features only; intentionally has no task identity/text."""

    sequence_index: int
    context_bytes: int
    size_bin: SizeBin

    @classmethod
    def from_context_bytes(cls, sequence_index: int, context_bytes: int,
                           *, large_threshold_bytes: int = 32_768) -> "RequestFeatures":
        if sequence_index < 1 or context_bytes < 0 or large_threshold_bytes < 1:
            raise ValueError("sequence_index, context_bytes, and threshold are out of range")
        size_bin = SizeBin.LARGE if context_bytes >= large_threshold_bytes else SizeBin.SMALL
        return cls(sequence_index, context_bytes, size_bin)


@dataclass(frozen=True)
class Candidate:
    configuration_id: str
    executable: bool
    context_window_eligible: bool

    @property
    def eligible(self) -> bool:
        return self.executable and self.context_window_eligible


@dataclass(frozen=True)
class Estimate:
    value: float | None
    provenance: Provenance
    observation_count: int

    def __post_init__(self) -> None:
        if self.value is not None and self.value < 0:
            raise ValueError("estimate value must be nonnegative")
        if self.observation_count < 0:
            raise ValueError("observation_count must be nonnegative")
        if self.value is None and self.provenance is not Provenance.UNAVAILABLE:
            raise ValueError("missing estimate must have unavailable provenance")


@dataclass(frozen=True)
class EstimateKey:
    configuration_id: str
    size_bin: SizeBin


@dataclass(frozen=True)
class PerformanceEstimate:
    latency_ms: Estimate
    total_tokens: Estimate


@dataclass(frozen=True)
class TokenUsage:
    value: int | None
    provenance: Provenance


@dataclass(frozen=True)
class Observation:
    configuration_id: str
    size_bin: SizeBin
    status: str
    end_to_end_duration_ms: float | None
    tokens: TokenUsage
    evaluation_observation: bool = False

    @property
    def valid(self) -> bool:
        return self.status == "success" and self.end_to_end_duration_ms is not None and self.end_to_end_duration_ms >= 0


@dataclass
class PolicyState:
    arm: str
    version: str
    calibration: dict[EstimateKey, PerformanceEstimate] = field(default_factory=dict)
    estimates: dict[EstimateKey, PerformanceEstimate] = field(default_factory=dict)
    recent_observations: dict[EstimateKey, list[Observation]] = field(default_factory=dict)
    incumbent: str | None = None
    last_switch_sequence: int | None = None
    probe_count: int = 0

    def record(self, observation: Observation, *, adaptive: bool) -> None:
        key = EstimateKey(observation.configuration_id, observation.size_bin)
        self.recent_observations.setdefault(key, []).append(observation)
        if not adaptive or not observation.evaluation_observation or not observation.valid:
            return
        valid = [item for item in self.recent_observations[key]
                 if item.evaluation_observation and item.valid][-5:]
        if len(valid) < 3:
            return
        latency = Estimate(sum(x.end_to_end_duration_ms for x in valid if x.end_to_end_duration_ms is not None) / len(valid), Provenance.MEASURED, len(valid))
        token_observations = [x.tokens for x in valid if x.tokens.value is not None]
        tokens = (Estimate(sum(x.value for x in token_observations if x.value is not None) / len(token_observations),
                           token_observations[-1].provenance, len(token_observations))
                  if token_observations else Estimate(None, Provenance.UNAVAILABLE, 0))
        self.estimates[key] = PerformanceEstimate(latency, tokens)


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


def estimate_from_observations(observations: list[Observation]) -> PerformanceEstimate:
    valid = [item for item in observations if item.valid][-5:]
    latency = (Estimate(sum(x.end_to_end_duration_ms for x in valid if x.end_to_end_duration_ms is not None) / len(valid), Provenance.MEASURED, len(valid))
               if valid else Estimate(None, Provenance.UNAVAILABLE, 0))
    token_obs = [x.tokens for x in valid if x.tokens.value is not None]
    tokens = (Estimate(sum(x.value for x in token_obs if x.value is not None) / len(token_obs), token_obs[-1].provenance, len(token_obs))
              if token_obs else Estimate(None, Provenance.UNAVAILABLE, 0))
    return PerformanceEstimate(latency, tokens)
