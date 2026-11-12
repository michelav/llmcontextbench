"""Versioned estimators for candidate observations partitioned by declared dataset features."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Protocol

from ctxbench.dataset.capabilities import RequestFeatureSchema

from .types import Estimate, Observation, PerformanceEstimate, Provenance, unavailable_estimate

Scalar = str | int | float | bool


@dataclass(frozen=True, slots=True)
class FeaturePartitionKey:
    schema_id: str
    schema_version: str
    values: tuple[tuple[str, Scalar], ...]

    def __post_init__(self) -> None:
        if not self.schema_id or not self.schema_version:
            raise ValueError("partition key requires a feature schema identity")
        names = [name for name, _ in self.values]
        if len(names) != len(set(names)):
            raise ValueError("partition key feature names must be unique")
        for name, value in self.values:
            if not name or not isinstance(value, (str, int, float, bool)):
                raise ValueError("partition values must be named scalar values")
            if isinstance(value, float) and not isfinite(value):
                raise ValueError("partition values must be finite")

    @classmethod
    def from_features(
        cls, schema: RequestFeatureSchema, features: dict[str, object]
    ) -> "FeaturePartitionKey | None":
        values = schema.partition_for(features)
        if values is None:
            return None
        return cls(schema.schema_id, schema.version, values)


@dataclass(frozen=True, slots=True)
class EstimatorDefinition:
    estimator_id: str = "rolling_window_mean"
    version: str = "1"
    window_size: int = 5
    minimum_observations: int = 3
    accepted_status: str = "success"

    def __post_init__(self) -> None:
        if not self.estimator_id or not self.version or not self.accepted_status:
            raise ValueError("estimator identity and status must be nonempty")
        if type(self.window_size) is not int or self.window_size < 1:
            raise ValueError("estimator window_size must be positive")
        if (type(self.minimum_observations) is not int or self.minimum_observations < 1
                or self.minimum_observations > self.window_size):
            raise ValueError("minimum_observations must be between one and window_size")


class Estimator(Protocol):
    definition: EstimatorDefinition

    def observe(self, configuration_id: str, partition: FeaturePartitionKey, observation: Observation) -> None: ...

    def estimate(
        self, configuration_id: str, partition: FeaturePartitionKey,
        calibration: PerformanceEstimate | None = None,
    ) -> PerformanceEstimate: ...


@dataclass(slots=True)
class RollingWindowEstimator:
    """Bounded per-candidate estimates with an explicit calibration warm-up rule."""

    definition: EstimatorDefinition = field(default_factory=EstimatorDefinition)
    _observations: dict[tuple[str, FeaturePartitionKey], list[Observation]] = field(default_factory=dict)

    def observe(self, configuration_id: str, partition: FeaturePartitionKey, observation: Observation) -> None:
        if not configuration_id or observation.configuration_id != configuration_id:
            raise ValueError("observation configuration does not match estimator key")
        key = (configuration_id, partition)
        rows = self._observations.setdefault(key, [])
        if observation.status == self.definition.accepted_status:
            rows.append(observation)
            del rows[:-self.definition.window_size]

    def estimate(
        self,
        configuration_id: str,
        partition: FeaturePartitionKey,
        calibration: PerformanceEstimate | None = None,
    ) -> PerformanceEstimate:
        rows = self._observations.get((configuration_id, partition), [])
        runtime = _estimate(rows)
        fallback = calibration or unavailable_estimate()
        minimum = self.definition.minimum_observations
        return PerformanceEstimate(
            runtime.latency_ms if runtime.latency_ms.observation_count >= minimum else fallback.latency_ms,
            runtime.total_tokens if runtime.total_tokens.observation_count >= minimum else fallback.total_tokens,
        )

    def observation_count(self, configuration_id: str, partition: FeaturePartitionKey) -> int:
        return len(self._observations.get((configuration_id, partition), ()))


def _estimate(observations: list[Observation]) -> PerformanceEstimate:
    return PerformanceEstimate(
        _mean((row.end_to_end_duration_ms, row.duration_provenance) for row in observations
              if row.end_to_end_duration_ms is not None),
        _mean((row.tokens.value, row.tokens.provenance) for row in observations
              if row.tokens.value is not None),
    )


def _mean(values) -> Estimate:
    items = list(values)
    if not items:
        return unavailable_estimate().latency_ms
    provenance = tuple(item[1] for item in items)
    result_provenance = Provenance.ESTIMATED if Provenance.ESTIMATED in provenance else Provenance.DERIVED
    return Estimate(
        sum(value for value, _ in items) / len(items),
        result_provenance,
        len(items),
        provenance,
    )
