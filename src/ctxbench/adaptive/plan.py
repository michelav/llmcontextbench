"""Frozen adaptive plan domain types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ctxbench.adaptive.state import WindowSpec
from ctxbench.adaptive.policy import PolicyReference
from ctxbench.dataset.provenance import DatasetProvenance


ADAPTIVE_PLAN_VERSION = 4


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    candidate_id: str
    model_id: str
    provider: str
    model_name: str
    model_params: Mapping[str, Any]
    configuration_id: str
    configuration: Mapping[str, str]
    surface_spec: Mapping[str, Any]
    execution_options: Mapping[str, Any] = field(default_factory=dict)
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlannedRequest:
    request_id: str
    sequence_index: int
    task_id: str
    instance_id: str
    task_statement: str
    task_template: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    task_tags: tuple[str, ...] = ()
    validation_type: str | None = None
    validation_config: Mapping[str, Any] = field(default_factory=dict)
    context_blocks: tuple[str, ...] = ()
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AdaptivePlan:
    workflow_id: str
    seed: int
    labels: Mapping[str, str]
    candidates: tuple[CandidateSpec, ...]
    requests: tuple[PlannedRequest, ...]
    workload_source: Mapping[str, Any]
    policy: PolicyReference
    window: WindowSpec
    acceptance: Mapping[str, Any]
    signals: tuple[Mapping[str, Any], ...] = ()
    goals: tuple[Mapping[str, Any], ...] = ()
    disturbances: tuple[Mapping[str, Any], ...] = ()
    evaluation: Mapping[str, Any] = field(default_factory=dict)
    trace: Mapping[str, Any] = field(default_factory=dict)
    allow_mixed_models: bool = False
    schema_version: int = ADAPTIVE_PLAN_VERSION
    dataset: DatasetProvenance | None = None  # runtime binding; dataset is canonical in manifest
    provenance: Mapping[str, Any] = field(default_factory=dict)
    resolved_definition: Mapping[str, Any] = field(default_factory=dict)
    execution_fingerprint: str = ""  # runtime binding; fingerprint is canonical in manifest

    def __post_init__(self) -> None:
        if self.schema_version != ADAPTIVE_PLAN_VERSION:
            raise ValueError(f"unsupported adaptive plan version {self.schema_version}")
        if not self.workflow_id or type(self.seed) is not int:
            raise ValueError("adaptive plan requires an ID and integer seed")
        if not self.candidates:
            raise ValueError("adaptive candidate catalogue must not be empty")
        if not self.requests:
            raise ValueError("adaptive workload must not be empty")
        candidate_ids = [row.candidate_id for row in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate IDs must be unique")
        request_ids = [row.request_id for row in self.requests]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("request IDs must be unique")
        if [row.sequence_index for row in self.requests] != list(range(1, len(self.requests) + 1)):
            raise ValueError("workload sequence indices must be contiguous and ordered")
        model_ids = {row.model_id for row in self.candidates}
        if len(model_ids) > 1 and not self.allow_mixed_models:
            raise ValueError("adaptive candidates must use one model unless allowMixedModels is true")
