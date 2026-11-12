"""Versioned provenance and compatibility checks for frozen adaptive Knowledge."""
from __future__ import annotations

from dataclasses import dataclass

from .estimator import EstimatorDefinition, FeaturePartitionKey
from .sensors import SensorClass
from .types import PerformanceEstimate, Provenance


@dataclass(frozen=True, slots=True)
class CalibrationQualitySource:
    metric_id: str
    assessor_id: str
    sensor_class: SensorClass
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.metric_id or not self.assessor_id:
            raise ValueError("calibration quality source requires metric and assessor IDs")
        if self.provenance == Provenance.UNAVAILABLE:
            raise ValueError("unavailable quality cannot seed calibration estimates")


@dataclass(frozen=True, slots=True)
class CalibrationProvenance:
    source_run_id: str
    source_artifact_fingerprint: str
    dataset_id: str
    dataset_version: str
    candidate_catalog_fingerprint: str
    feature_schema_id: str
    feature_schema_version: str
    estimator: EstimatorDefinition
    source_request_ids: tuple[str, ...]
    quality_sources: tuple[CalibrationQualitySource, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        required = (self.source_run_id, self.source_artifact_fingerprint, self.dataset_id,
                    self.dataset_version, self.candidate_catalog_fingerprint,
                    self.feature_schema_id, self.feature_schema_version)
        if any(not value for value in required):
            raise ValueError("calibration provenance fields must be nonempty")
        if self.schema_version != 1:
            raise ValueError("unsupported calibration provenance schema")
        if not self.source_request_ids or any(not value for value in self.source_request_ids):
            raise ValueError("calibration requires identified source requests")
        if len(set(self.source_request_ids)) != len(self.source_request_ids):
            raise ValueError("calibration source request IDs must be unique")

    def validate_for(
        self,
        *,
        active_request_ids: set[str],
        dataset_id: str,
        dataset_version: str,
        candidate_catalog_fingerprint: str,
        feature_schema_id: str,
        feature_schema_version: str,
        estimator: EstimatorDefinition,
    ) -> None:
        overlap = active_request_ids.intersection(self.source_request_ids)
        if overlap:
            raise ValueError(f"calibration requests overlap the active workload: {', '.join(sorted(overlap))}")
        expected = (
            (self.dataset_id, dataset_id, "dataset identity"),
            (self.dataset_version, dataset_version, "dataset version"),
            (self.candidate_catalog_fingerprint, candidate_catalog_fingerprint, "candidate catalog"),
            (self.feature_schema_id, feature_schema_id, "feature schema ID"),
            (self.feature_schema_version, feature_schema_version, "feature schema version"),
            (self.estimator, estimator, "estimator definition"),
        )
        for source, target, label in expected:
            if source != target:
                raise ValueError(f"calibration {label} does not match the active workflow")


@dataclass(frozen=True, slots=True)
class CalibrationEstimate:
    configuration_id: str
    partition: FeaturePartitionKey
    estimate: PerformanceEstimate

    def __post_init__(self) -> None:
        if not self.configuration_id:
            raise ValueError("calibration estimate requires a candidate configuration")


@dataclass(frozen=True, slots=True)
class CalibrationArtifact:
    provenance: CalibrationProvenance
    estimates: tuple[CalibrationEstimate, ...]

    def __post_init__(self) -> None:
        if not self.estimates:
            raise ValueError("calibration artifact must contain at least one estimate")
        keys = [(row.configuration_id, row.partition) for row in self.estimates]
        if len(keys) != len(set(keys)):
            raise ValueError("calibration estimate keys must be unique")
        if any(row.partition.schema_id != self.provenance.feature_schema_id
               or row.partition.schema_version != self.provenance.feature_schema_version
               for row in self.estimates):
            raise ValueError("calibration estimate partition does not match feature schema provenance")

    def estimate_for(
        self, configuration_id: str, partition: FeaturePartitionKey
    ) -> PerformanceEstimate | None:
        return next((row.estimate for row in self.estimates
                     if row.configuration_id == configuration_id and row.partition == partition), None)
