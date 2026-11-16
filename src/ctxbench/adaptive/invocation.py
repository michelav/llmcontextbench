"""Build runtime invocations at decision time from a frozen request and candidate."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ctxbench.adaptive.plan import AdaptivePlan, CandidateSpec, PlannedRequest
from ctxbench.execution.service import ExecutionRequest


def build_execution_request(plan: AdaptivePlan, request: PlannedRequest, candidate: CandidateSpec,
                            execution_fingerprint: str) -> ExecutionRequest:
    configuration = dict(candidate.configuration)
    runtime_payload = {
        "task": request.task_statement,
        "provider": candidate.provider,
        "model_name": candidate.model_name,
        "configuration": configuration,
        "surface_spec": dict(candidate.surface_spec),
        "params": {**dict(candidate.execution_options), **dict(candidate.model_params)},
        "metadata": {"taskTemplate": request.task_template, "parameters": dict(request.parameters)},
    }
    result_metadata = {
        "experimentId": plan.workflow_id,
        "dataset": plan.dataset.model_dump(mode="json"),
        "candidateId": candidate.candidate_id,
        "configurationId": candidate.configuration_id,
        "modelId": candidate.model_id,
        "taskTags": list(request.task_tags),
        "validationType": request.validation_type,
        "validationConfig": dict(request.validation_config),
        "parameters": dict(request.parameters),
        "contextBlocks": list(request.context_blocks),
        "traceOptions": dict(plan.trace),
    }
    return ExecutionRequest(
        execution_id=request.request_id,
        workflow_id=plan.workflow_id,
        correlation_id=request.request_id,
        experiment_id=plan.workflow_id,
        execution_fingerprint=execution_fingerprint,
        task_id=request.task_id,
        instance_id=request.instance_id,
        candidate_id=candidate.candidate_id,
        payload={"runtimeRequest": runtime_payload, "resultMetadata": result_metadata},
    )
