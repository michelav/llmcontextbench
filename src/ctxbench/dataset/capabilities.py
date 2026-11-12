from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Literal

from ctxbench.dataset.package import DatasetMetadata, StrategyDescriptor

MetricProvenance = Literal["reported", "measured", "derived", "estimated", "unavailable"]
FeatureType = Literal["number", "category", "boolean"]
SensorClass = Literal["response_acceptance", "runtime", "semantic_proxy", "judge", "oracle"]


@dataclass(frozen=True, slots=True)
class FeatureCapability:
    """One pre-execution feature a dataset can expose to a declared controller schema."""

    feature_id: str
    value_type: FeatureType
    provenance: MetricProvenance
    unit: str | None = None
    categories: tuple[str, ...] = ()
    partitionable: bool = True

    def __post_init__(self) -> None:
        if not self.feature_id or self.provenance == "unavailable":
            raise ValueError("feature capabilities require an ID and available provenance")
        if self.value_type not in {"number", "category", "boolean"}:
            raise ValueError("unsupported feature value_type")
        if self.provenance not in {"reported", "measured", "derived", "estimated"}:
            raise ValueError("invalid feature provenance")
        normalized_id = self.feature_id.lower().replace("-", "_")
        if normalized_id in {
            "task_id", "instance_id", "request_id", "trial_id", "execution_id",
            "candidate_id", "response", "answer", "status", "outcome", "success",
        }:
            raise ValueError(f"identity and outcome field {self.feature_id!r} cannot be a request feature")
        if self.value_type == "category" and len(self.categories) != len(set(self.categories)):
            raise ValueError("feature categories must be unique")
        if self.value_type != "category" and self.categories:
            raise ValueError("only category features declare categories")


@dataclass(frozen=True, slots=True)
class FeaturePartitionCapability:
    """A stable, named partition for one declared feature."""

    feature_id: str
    boundaries: tuple[float, ...] = ()
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.feature_id:
            raise ValueError("partition feature_id must be nonempty")
        if self.boundaries:
            if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v)
                    for v in self.boundaries)
                    or tuple(sorted(self.boundaries)) != self.boundaries
                    or len(set(self.boundaries)) != len(self.boundaries)
                    or len(self.labels) != len(self.boundaries) + 1
                    or any(not label for label in self.labels)):
                raise ValueError("numeric partitions require ordered boundaries and one label per bucket")
        elif self.labels:
            raise ValueError("partition labels require numeric boundaries")

    def assign(self, value: object) -> str | int | float | bool | None:
        if value is None:
            return None
        if not self.boundaries:
            if isinstance(value, (str, int, float, bool)):
                return value
            raise ValueError(f"Feature {self.feature_id} must be a scalar")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError(f"Feature {self.feature_id} requires a finite number for partitioning")
        for index, boundary in enumerate(self.boundaries):
            if value <= boundary:
                return self.labels[index]
        return self.labels[-1]


@dataclass(frozen=True, slots=True)
class RequestFeatureSchema:
    schema_id: str
    version: str
    features: tuple[FeatureCapability, ...]
    partition_keys: tuple[str, ...] = ()
    partitions: tuple[FeaturePartitionCapability, ...] = ()
    missing_partition_policy: Literal["unpartitioned", "explicit"] = "unpartitioned"

    def __post_init__(self) -> None:
        if not self.schema_id or not self.version:
            raise ValueError("feature schema requires an ID and version")
        if self.missing_partition_policy not in {"unpartitioned", "explicit"}:
            raise ValueError("unsupported missing partition policy")
        ids = [feature.feature_id for feature in self.features]
        if len(ids) != len(set(ids)):
            raise ValueError("feature IDs must be unique")
        by_id = {feature.feature_id: feature for feature in self.features}
        if len(self.partition_keys) != len(set(self.partition_keys)):
            raise ValueError("partition keys must be unique")
        if any(key not in by_id or not by_id[key].partitionable for key in self.partition_keys):
            raise ValueError("partition keys must reference partitionable declared features")
        rules = [rule.feature_id for rule in self.partitions]
        if len(rules) != len(set(rules)) or any(key not in self.partition_keys for key in rules):
            raise ValueError("partition rules must uniquely reference declared partition keys")
        for rule in self.partitions:
            feature = by_id[rule.feature_id]
            if rule.boundaries and feature.value_type != "number":
                raise ValueError("numeric boundaries require a numeric feature")

    def partition_for(self, values: dict[str, object]) -> tuple[tuple[str, object], ...] | None:
        declared = {feature.feature_id: feature for feature in self.features}
        unknown = set(values) - set(declared)
        if unknown:
            raise ValueError(f"Undeclared request features: {', '.join(sorted(unknown))}")
        for key, value in values.items():
            feature = declared[key]
            if value is not None and not _matches_feature_type(feature.value_type, value):
                raise ValueError(f"Request feature {key} does not match {feature.value_type}")
            if value is not None and feature.value_type == "category" and feature.categories and value not in feature.categories:
                raise ValueError(f"Request feature {key} has an undeclared category")
        if not self.partition_keys:
            return ()
        if any(key not in values or values[key] is None for key in self.partition_keys):
            if self.missing_partition_policy == "unpartitioned":
                return None
        rules = {rule.feature_id: rule for rule in self.partitions}
        output = []
        for key in self.partition_keys:
            value = values.get(key)
            if value is None:
                output.append((key, "__missing__"))
                continue
            rule = rules.get(key)
            output.append((key, rule.assign(value) if rule else value))
        return tuple(output)


@dataclass(frozen=True, slots=True)
class SignalCost:
    duration_ms: float | None
    duration_provenance: MetricProvenance
    total_tokens: int | None
    token_provenance: MetricProvenance

    def __post_init__(self) -> None:
        _validate_capability_metric(self.duration_ms, self.duration_provenance)
        _validate_capability_metric(self.total_tokens, self.token_provenance)
        if self.total_tokens is not None and type(self.total_tokens) is not int:
            raise ValueError("sensor token costs must be integers")


@dataclass(frozen=True, slots=True)
class SignalCapability:
    signal_id: str
    version: str
    metric_id: str
    sensor_class: SensorClass
    value_provenance: MetricProvenance
    cost: SignalCost
    value_scale: str | None = None
    uses_reference_data: bool = False
    deployment_scope: str = "runtime"

    def __post_init__(self) -> None:
        if not self.signal_id or not self.version or not self.metric_id or not self.deployment_scope:
            raise ValueError("signal capability identity fields must be nonempty")
        if self.sensor_class not in {"response_acceptance", "runtime", "semantic_proxy", "judge", "oracle"}:
            raise ValueError("unsupported sensor class")
        if self.value_provenance not in {"reported", "measured", "derived", "estimated", "unavailable"}:
            raise ValueError("invalid signal provenance")
        if self.value_provenance == "unavailable":
            raise ValueError("a declared signal capability must have an available value provenance")
        if self.sensor_class in {"judge", "oracle"} and not self.uses_reference_data:
            raise ValueError("judge and oracle signals must declare reference-data use")


def _matches_feature_type(value_type: FeatureType, value: object) -> bool:
    if value_type == "number":
        return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value)
    if value_type == "category":
        return isinstance(value, str)
    return type(value) is bool


def _validate_capability_metric(value, provenance: MetricProvenance) -> None:
    if (value is None) != (provenance == "unavailable"):
        raise ValueError("unavailable capability costs require unavailable provenance")
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not isfinite(value) or value < 0
    ):
        raise ValueError("capability costs must be finite and nonnegative")
    if provenance not in {"reported", "measured", "derived", "estimated", "unavailable"}:
        raise ValueError("invalid metric provenance")


_MINIMUM_RESPONSE_LENGTH = SignalCapability(
    signal_id="minimum_response_length",
    version="1",
    metric_id="response_accepted",
    sensor_class="response_acceptance",
    value_provenance="derived",
    cost=SignalCost(None, "unavailable", 0, "measured"),
    value_scale="boolean",
)
DEFAULT_RESPONSE_ACCEPTANCE_SENSORS = (_MINIMUM_RESPONSE_LENGTH,)


@dataclass(slots=True)
class DatasetCapabilityReport:
    identity: str
    version: str
    origin: str | None
    resolved_revision: str | None
    materialized_path: str | None
    content_hash: str | None
    metadata: DatasetMetadata
    mandatory_capabilities: dict[str, bool]
    optional_capabilities: dict[str, bool]
    contributed_tools: object | None
    evaluation_helpers: object | None
    strategy_descriptors: list[StrategyDescriptor]
    missing_mandatory: list[str]
    nonconformant_descriptors: list[str]
    conformant: bool
    request_feature_schema: RequestFeatureSchema | None = None
    response_acceptance_sensors: tuple[SignalCapability, ...] = field(
        default_factory=lambda: DEFAULT_RESPONSE_ACCEPTANCE_SENSORS
    )
    semantic_quality_assessors: tuple[SignalCapability, ...] = ()

    def __post_init__(self) -> None:
        if self.request_feature_schema is not None and not isinstance(self.request_feature_schema, RequestFeatureSchema):
            raise ValueError("request_feature_schema must be a RequestFeatureSchema")
        for signals, label in (
            (self.response_acceptance_sensors, "response acceptance sensors"),
            (self.semantic_quality_assessors, "semantic quality assessors"),
        ):
            if any(not isinstance(signal, SignalCapability) for signal in signals):
                raise ValueError(f"{label} must be SignalCapability records")
            if len({signal.signal_id for signal in signals}) != len(signals):
                raise ValueError(f"{label} IDs must be unique")
