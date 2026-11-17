"""Typed response-acceptance and semantic-quality observations for adaptive control."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import importlib
import inspect
from math import isfinite
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Mapping, Protocol, Sequence

from ctxbench.dataset.capabilities import SignalCapability
from ctxbench.core.errors import CapabilityUnavailableError
from ctxbench.core.fingerprint import digest, file_digest

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

    def assess(self, item: "AssessmentInput") -> QualityObservation: ...


@dataclass(frozen=True, slots=True)
class AssessmentInput:
    request_id: str
    task_id: str
    instance_id: str
    candidate_id: str
    response: str


@dataclass(frozen=True, slots=True)
class ResolvedAssessor:
    signal: Mapping[str, Any]
    assessor: OnlineQualityAssessor
    capability: SignalCapability


def resolve_quality_assessors(
    signals: Sequence[Mapping[str, Any]], package: object, *,
    plugin_paths: Sequence[str | Path] = (), expected: bool = False,
) -> tuple[ResolvedAssessor, ...]:
    """Resolve declared quality sensors and validate their frozen capability contract."""
    report = package.capability_report()
    capabilities = {item.signal_id: item for item in report.semantic_quality_assessors}
    resolved: list[ResolvedAssessor] = []
    seen_signal_ids: set[str] = set()
    for row in signals:
        signal_id = str(row.get("id", ""))
        if not signal_id.startswith("quality.") or not signal_id.partition(".")[2]:
            raise ValueError("online quality signal IDs must use 'quality.<metric_id>'")
        if signal_id in seen_signal_ids:
            raise ValueError(f"Duplicate quality signal ID {signal_id!r}")
        seen_signal_ids.add(signal_id)
        metric_id = signal_id.partition(".")[2]
        ref = str(row.get("assessor", ""))
        if not ref:
            raise ValueError(f"Quality signal {signal_id!r} requires an assessor reference")
        source_digest = None
        if ":" in ref:
            try:
                assessor, capability, source_digest = _load_external_assessor(ref, plugin_paths)
            except Exception as exc:
                raise ValueError(f"Could not resolve online assessor {ref!r}: {exc}") from exc
        else:
            capability = capabilities.get(ref)
            if capability is None:
                raise CapabilityUnavailableError(
                    f"Dataset does not declare online assessor {ref!r} for {signal_id!r}"
                )
            factory = getattr(package, "online_assessor", None)
            assessor = factory(ref) if callable(factory) else None
            if assessor is None:
                raise CapabilityUnavailableError(
                    f"Dataset declares assessor {ref!r} but does not provide an online implementation"
                )
            actual = getattr(assessor, "capability", None)
            if actual != capability:
                raise ValueError(f"Online assessor {ref!r} capability differs from its dataset declaration")
            source = inspect.getsourcefile(type(assessor))
            if not source:
                raise ValueError(f"Could not locate source for dataset online assessor {ref!r}")
            source_path = Path(source).resolve()
            source_digest = digest([(source_path.name, file_digest(source_path))])
        if capability.metric_id != metric_id:
            raise ValueError(
                f"Quality signal {signal_id!r} does not match assessor metric {capability.metric_id!r}"
            )
        frozen = {
            **dict(row),
            "metricId": capability.metric_id,
            "assessorVersion": capability.version,
            "sensorClass": capability.sensor_class,
            "valueProvenance": capability.value_provenance,
            "valueScale": capability.value_scale or "unit",
            "usesReferenceData": capability.uses_reference_data,
            "declaredCost": {
                "durationMs": capability.cost.duration_ms,
                "durationProvenance": capability.cost.duration_provenance,
                "totalTokens": capability.cost.total_tokens,
                "tokenProvenance": capability.cost.token_provenance,
            },
        }
        if source_digest is not None:
            if expected and row.get("sourceDigest") != source_digest:
                raise ValueError("Online assessor source changed since planning; create a fresh adaptive plan.")
            frozen["sourceDigest"] = source_digest
        if expected:
            for key in ("metricId", "assessorVersion", "sensorClass", "valueProvenance",
                        "valueScale", "usesReferenceData", "declaredCost"):
                if row.get(key) != frozen.get(key):
                    raise ValueError("Online assessor capability changed since planning; create a fresh adaptive plan.")
        resolved.append(ResolvedAssessor(frozen, assessor, capability))
    if expected and len(resolved) != len(signals):
        raise ValueError("Frozen online assessor declarations could not be resolved")
    return tuple(resolved)


def _load_external_assessor(ref: str, plugin_paths: Sequence[str | Path]):
    module_name, class_name = ref.split(":", 1)
    if not module_name or not class_name:
        raise ValueError("External assessor reference must use 'module:ClassName'")
    paths = [str(Path(path).expanduser().resolve()) for path in plugin_paths]
    old_path = list(sys.path)
    previous_module = sys.modules.pop(module_name, None)
    try:
        for path in reversed(paths):
            if path not in sys.path:
                sys.path.insert(0, path)
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name, None)
        if not inspect.isclass(cls):
            raise ValueError(f"Online assessor class not found: {ref}")
        instance = cls()
        capability = getattr(instance, "capability", None)
        source = inspect.getsourcefile(cls) or getattr(module, "__file__", None)
        if not isinstance(capability, SignalCapability) or not source:
            raise ValueError(f"Online assessor {ref!r} must expose a SignalCapability and source file")
        source_path = Path(source).resolve()
        return instance, capability, digest([(source_path.name, file_digest(source_path))])
    finally:
        sys.modules.pop(module_name, None)
        if previous_module is not None:
            sys.modules[module_name] = previous_module
        sys.path[:] = old_path


def assess_quality(
    resolved: ResolvedAssessor, item: AssessmentInput, *, clock=perf_counter,
) -> tuple[QualityObservation, dict[str, Any]]:
    """Run one assessor, validate its result and always measure assessor wall time."""
    capability = resolved.capability
    started = clock()
    error_type = None
    try:
        observation = resolved.assessor.assess(item)
        if not isinstance(observation, QualityObservation):
            raise ValueError("assessor must return QualityObservation")
        _validate_quality_observation(observation, item, capability)
    except Exception as exc:
        error_type = type(exc).__name__
        observation = QualityObservation.unavailable(
            request_id=item.request_id, candidate_id=item.candidate_id,
            metric_id=capability.metric_id, value_scale=capability.value_scale or "unit",
            assessor_id=capability.signal_id, assessor_version=capability.version,
            sensor_class=SensorClass(capability.sensor_class),
            uses_reference_data=capability.uses_reference_data,
        )
    duration_ms = max(0.0, (clock() - started) * 1000)
    token_usage = TokenUsage(
        observation.cost.tokens.value,
        Provenance(observation.cost.tokens.provenance),
    )
    cost = SensorCost(duration_ms, Provenance.MEASURED, token_usage)
    normalized = QualityObservation(
        request_id=item.request_id, candidate_id=item.candidate_id, metric_id=capability.metric_id,
        value=observation.value, value_scale=capability.value_scale or "unit",
        assessor_id=capability.signal_id, assessor_version=capability.version,
        sensor_class=SensorClass(capability.sensor_class), provenance=Provenance(observation.provenance),
        cost=cost, uses_reference_data=capability.uses_reference_data,
    )
    cost_record = {
        "signalId": str(resolved.signal["id"]), "assessorId": capability.signal_id,
        "assessorVersion": capability.version, "durationMs": duration_ms,
        "durationProvenance": Provenance.MEASURED.value,
        "totalTokens": cost.tokens.value, "tokenProvenance": cost.tokens.provenance.value,
    }
    if error_type:
        cost_record["errorType"] = error_type
    return normalized, cost_record


def _validate_quality_observation(
    observation: QualityObservation, item: AssessmentInput, capability: SignalCapability,
) -> None:
    if not isinstance(observation.cost, SensorCost) or not isinstance(observation.cost.tokens, TokenUsage):
        raise ValueError("quality observation must report typed assessor cost")
    expected_identity = (item.request_id, item.candidate_id, capability.metric_id, capability.signal_id,
                         capability.version, capability.value_scale or "unit", SensorClass(capability.sensor_class),
                         capability.uses_reference_data)
    actual_identity = (observation.request_id, observation.candidate_id, observation.metric_id,
                       observation.assessor_id, observation.assessor_version, observation.value_scale,
                       observation.sensor_class, observation.uses_reference_data)
    expected_provenance = (Provenance.UNAVAILABLE if observation.value is None
                           else Provenance(capability.value_provenance))
    scale = (capability.value_scale or "unit").lower().replace(" ", "")
    scale_is_valid = True
    if observation.value is not None and scale in {"binary", "bool", "boolean", "0/1"}:
        scale_is_valid = observation.value in {0, 1}
    elif observation.value is not None and scale in {"0..1", "0-1", "[0,1]"}:
        scale_is_valid = 0 <= observation.value <= 1
    if actual_identity != expected_identity or observation.provenance != expected_provenance or not scale_is_valid:
        raise ValueError("quality observation does not match its declared assessor capability")


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
