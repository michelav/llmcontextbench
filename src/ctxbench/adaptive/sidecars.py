"""Versioned sidecar contracts only; no canonical artifact changes or file I/O."""
from dataclasses import asdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .types import Decision, Provenance, SizeBin, validate_metric


class SidecarModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True, serialize_by_alias=True)

    # Explicitly default to aliases also on older supported Pydantic versions.
    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)

    def model_dump_json(self, **kwargs: Any) -> str:
        kwargs.setdefault("by_alias", True)
        return super().model_dump_json(**kwargs)


class MetricRecord(SidecarModel):
    value: float | None
    provenance: Provenance
    observation_count: int = Field(ge=0, alias="observationCount")
    source_provenance: tuple[Provenance, ...] = Field(default=(), alias="sourceProvenance")

    @model_validator(mode="after")
    def validate_value(self):
        validate_metric(self.value, self.provenance)
        return self


class TokenRecord(SidecarModel):
    value: int | None
    provenance: Provenance

    @model_validator(mode="after")
    def validate_value(self):
        validate_metric(self.value, self.provenance)
        return self


class EstimateRecord(SidecarModel):
    latency_ms: MetricRecord = Field(alias="latencyMs")
    total_tokens: MetricRecord = Field(alias="totalTokens")


class FeatureRecord(SidecarModel):
    sequence_index: int = Field(ge=1, alias="sequenceIndex")
    context_bytes: int = Field(ge=0, alias="contextBytes")
    size_bin: SizeBin = Field(alias="sizeBin")


class ContextFitRecord(SidecarModel):
    input_tokens: int = Field(ge=0, alias="inputTokens")
    output_reservation: int = Field(ge=0, alias="outputReservation")
    context_limit: int = Field(ge=0, alias="contextLimit")
    provenance: Literal[Provenance.DERIVED, Provenance.ESTIMATED]


class CandidateRecord(SidecarModel):
    configuration_id: str = Field(alias="configurationId")
    executable: bool
    context_fit: ContextFitRecord = Field(alias="contextFit")
    eligible: bool
    eligibility_reasons: tuple[str, ...] = Field(alias="eligibilityReasons")


class DecisionRecord(SidecarModel):
    sequence_index: int = Field(ge=1, alias="sequenceIndex")
    features: FeatureRecord
    eligible_candidates: tuple[str, ...] = Field(alias="eligibleCandidates")
    candidates: tuple[CandidateRecord, ...]
    estimates: dict[str, EstimateRecord]
    selected_configuration: str | None = Field(alias="selectedConfiguration")
    normal_configuration: str | None = Field(alias="normalConfiguration")
    reason: str
    probe: bool
    cooldown_active: bool = Field(alias="cooldownActive")
    objective_attainment: Literal["met", "missed", "unknown"] = Field(alias="objectiveAttainment")

    @classmethod
    def from_decision(cls, decision: Decision) -> "DecisionRecord":
        data = asdict(decision)
        data["candidates"] = [dict(asdict(c), eligible=c.eligible,
                                   eligibility_reasons=c.eligibility_reasons) for c in decision.candidates]
        return cls.model_validate(data)


class DecisionSidecar(SidecarModel):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    request_id: str = Field(alias="requestId")
    trial_id: str | None = Field(alias="trialId")
    policy: str
    policy_version: str = Field(alias="policyVersion")
    decision: DecisionRecord
    status: Literal["selected", "success", "error", "unserved"]
    end_to_end_duration_ms: MetricRecord = Field(alias="endToEndDurationMs")
    tokens: TokenRecord
    error: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self):
        selected = self.decision.selected_configuration is not None
        if (self.status == "unserved") == selected:
            raise ValueError("unserved records require no selection; other outcomes require selection")
        if selected != (self.trial_id is not None):
            raise ValueError("trial identity requires an execution selection")
        if self.status == "error" and not self.error:
            raise ValueError("error outcome requires error details")
        duration = self.end_to_end_duration_ms
        if duration.value is not None and duration.provenance != Provenance.MEASURED:
            raise ValueError("outer duration must be measured")
        return self


class RunMetadata(SidecarModel):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    policy: str
    policy_version: str = Field(alias="policyVersion")
    scenario: str
    seed: int
    dataset_provenance: dict[str, Any] = Field(alias="datasetProvenance")
    model_provenance: dict[str, Any] = Field(alias="modelProvenance")
    configuration_catalog: dict[str, dict[str, Any]] = Field(alias="configurationCatalog")
    latency_objective_ms: float = Field(ge=0, allow_inf_nan=False, alias="latencyObjectiveMs")
    injection_schedule: tuple[dict[str, Any], ...] = Field(alias="injectionSchedule")
    cache_policy: dict[str, Any] = Field(alias="cachePolicy")
    code_revision: str = Field(alias="codeRevision")
