"""Typed response-acceptance and semantic-quality observations for adaptive control."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from time import perf_counter
from typing import Protocol

from ctxbench.dataset.capabilities import SignalCapability

from ctxbench.core.provenance import Provenance, TokenUsage


class SensorClass(StrEnum):
    RESPONSE_ACCEPTANCE = "response_acceptance"
    RUNTIME = "runtime"
    SEMANTIC_PROXY = "semantic_proxy"
    JUDGE = "judge"
    ORACLE = "oracle"


@dataclass(frozen=True, slots=True)
class SensorCost:
    duration_ms: float | None
    duration_provenance: Provenance
    tokens: TokenUsage

    def __post_init__(self) -> None:
        if (self.duration_ms is None) != (self.duration_provenance == Provenance.UNAVAILABLE):
            raise ValueError("unavailable sensor duration requires unavailable provenance")
        if self.duration_ms is not None and (not isfinite(self.duration_ms) or self.duration_ms < 0):
            raise ValueError("sensor duration must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class ResponseAcceptanceObservation:
    request_id: str
    candidate_id: str
    sensor_id: str
    sensor_version: str
    accepted: bool
    sensor_class: SensorClass
    provenance: Provenance
    cost: SensorCost

    def __post_init__(self) -> None:
        if not self.request_id or not self.candidate_id or not self.sensor_id or not self.sensor_version:
            raise ValueError("acceptance observation identity fields must be nonempty")
        if self.sensor_class != SensorClass.RESPONSE_ACCEPTANCE:
            raise ValueError("response acceptance must use the response_acceptance sensor class")
        if self.provenance == Provenance.UNAVAILABLE:
            raise ValueError("acceptance decisions cannot have unavailable provenance")


@dataclass(frozen=True, slots=True)
class QualityObservation:
    request_id: str
    candidate_id: str
    metric_id: str
    value: float | None
    value_scale: str
    assessor_id: str
    assessor_version: str
    sensor_class: SensorClass
    provenance: Provenance
    cost: SensorCost
    uses_reference_data: bool = False

    def __post_init__(self) -> None:
        if not all((self.request_id, self.candidate_id, self.metric_id, self.value_scale,
                    self.assessor_id, self.assessor_version)):
            raise ValueError("quality observation identity and scale fields must be nonempty")
        if (self.value is None) != (self.provenance == Provenance.UNAVAILABLE):
            raise ValueError("missing quality values require unavailable provenance")
        if self.value is not None and not isfinite(self.value):
            raise ValueError("quality values must be finite")
        if self.sensor_class in {SensorClass.JUDGE, SensorClass.ORACLE} and not self.uses_reference_data:
            raise ValueError("judge and oracle observations must declare reference-data use")

    @classmethod
    def unavailable(
        cls, *, request_id: str, candidate_id: str, metric_id: str, value_scale: str,
        assessor_id: str, assessor_version: str, sensor_class: SensorClass,
        uses_reference_data: bool = False,
    ) -> "QualityObservation":
        return cls(
            request_id=request_id,
            candidate_id=candidate_id,
            metric_id=metric_id,
            value=None,
            value_scale=value_scale,
            assessor_id=assessor_id,
            assessor_version=assessor_version,
            sensor_class=sensor_class,
            provenance=Provenance.UNAVAILABLE,
            cost=SensorCost(None, Provenance.UNAVAILABLE, TokenUsage(None, Provenance.UNAVAILABLE)),
            uses_reference_data=uses_reference_data,
        )


class OnlineQualityAssessor(Protocol):
    """Optional runtime evaluator. Dataset capability metadata declares its cost and evidence class."""

    @property
    def capability(self) -> SignalCapability: ...

    def assess(self, request_id: str, candidate_id: str, response: str) -> QualityObservation: ...


class MinimumResponseLengthSensor:
    """Deterministic response acceptance; this sensor does not claim semantic correctness."""

    sensor_id = "minimum_response_length"
    version = "1"

    def __init__(self, minimum_length: int, *, clock=perf_counter) -> None:
        if type(minimum_length) is not int or minimum_length < 0:
            raise ValueError("minimum response length must be a nonnegative integer")
        self.minimum_length = minimum_length
        self._clock = clock

    def observe(self, request_id: str, candidate_id: str, response: str) -> ResponseAcceptanceObservation:
        started = self._clock()
        accepted = len(response.strip()) >= self.minimum_length
        duration_ms = max(0.0, (self._clock() - started) * 1000)
        return ResponseAcceptanceObservation(
            request_id=request_id,
            candidate_id=candidate_id,
            sensor_id=self.sensor_id,
            sensor_version=self.version,
            accepted=accepted,
            sensor_class=SensorClass.RESPONSE_ACCEPTANCE,
            provenance=Provenance.DERIVED,
            cost=SensorCost(duration_ms, Provenance.MEASURED, TokenUsage(0, Provenance.DERIVED)),
        )


def assessor_from_capability(capability: SignalCapability) -> tuple[SensorClass, Provenance]:
    """Normalize dataset capability metadata at the adaptive boundary."""
    return SensorClass(capability.sensor_class), Provenance(capability.value_provenance)
