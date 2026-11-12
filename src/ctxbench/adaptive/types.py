from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Mapping

INLINE_CONFIGURATION = "inline-code-full"
LOCAL_MCP_CONFIGURATION = "local-mcp-repoqa-ops"
POLICY_VERSION = "2"


class SizeBin(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


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
    """Permitted features; identities and nominal variants belong to workload preparation."""
    sequence_index: int
    context_bytes: int
    size_bin: SizeBin | None = None

    def __post_init__(self) -> None:
        if (type(self.sequence_index) is not int or type(self.context_bytes) is not int
                or self.sequence_index < 1 or self.context_bytes < 0):
            raise ValueError("invalid request features")
        if self.size_bin is not None and not isinstance(self.size_bin, SizeBin):
            raise ValueError("size_bin must be a declared SizeBin or None")


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
class EstimateKey:
    configuration_id: str
    size_bin: SizeBin | None


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
    size_bin: SizeBin | None
    status: str
    end_to_end_duration_ms: float | None
    tokens: TokenUsage
    duration_provenance: Provenance = Provenance.MEASURED

    def __post_init__(self) -> None:
        if not self.configuration_id or (self.size_bin is not None and not isinstance(self.size_bin, SizeBin)):
            raise ValueError("observation requires a configuration and optional legacy SizeBin")
        validate_metric(self.end_to_end_duration_ms, self.duration_provenance)

    @property
    def valid(self) -> bool:
        return self.status == "success"


def unavailable_estimate() -> PerformanceEstimate:
    missing = Estimate(None, Provenance.UNAVAILABLE, 0)
    return PerformanceEstimate(missing, missing)


def _mean(values: list[tuple[float, Provenance]]) -> Estimate:
    if not values:
        return unavailable_estimate().latency_ms
    sources = tuple(p for _, p in values)
    provenance = Provenance.ESTIMATED if Provenance.ESTIMATED in sources else Provenance.DERIVED
    return Estimate(sum(v for v, _ in values) / len(values), provenance, len(values), sources)


def estimate_from_observations(observations: list[Observation]) -> PerformanceEstimate:
    if len({EstimateKey(o.configuration_id, o.size_bin) for o in observations}) > 1:
        raise ValueError("observations must belong to one configuration/bin")
    valid = [o for o in observations if o.valid][-5:]
    return PerformanceEstimate(
        _mean([(o.end_to_end_duration_ms, o.duration_provenance) for o in valid
               if o.end_to_end_duration_ms is not None]),
        _mean([(o.tokens.value, o.tokens.provenance) for o in valid if o.tokens.value is not None]))


@dataclass
class PolicyState:
    arm: str
    version: str = POLICY_VERSION
    calibration: dict[EstimateKey, PerformanceEstimate] = field(default_factory=dict)
    estimates: dict[EstimateKey, PerformanceEstimate] = field(default_factory=dict, init=False)
    recent_observations: dict[EstimateKey, list[Observation]] = field(default_factory=dict, init=False)
    incumbent: str | None = field(default=None, init=False)
    last_switch_sequence: int | None = field(default=None, init=False)
    probe_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.calibration = deepcopy(self.calibration)

    def record(self, observation: Observation) -> None:
        key = EstimateKey(observation.configuration_id, observation.size_bin)
        self.recent_observations.setdefault(key, []).append(observation)

    def update(self, key: EstimateKey) -> None:
        runtime = estimate_from_observations(self.recent_observations[key])
        fallback = self.calibration.get(key, unavailable_estimate())
        self.estimates[key] = PerformanceEstimate(
            runtime.latency_ms if runtime.latency_ms.observation_count >= 3 else fallback.latency_ms,
            runtime.total_tokens if runtime.total_tokens.observation_count >= 3 else fallback.total_tokens)


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
