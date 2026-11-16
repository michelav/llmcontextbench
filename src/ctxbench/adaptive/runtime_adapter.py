"""Translate adaptive execution payloads to the shared runtime without TrialSpec."""
from __future__ import annotations

from typing import Any

from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset.provenance import DatasetProvenance
from ctxbench.core.provisioning import ProvisioningConfiguration
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.adapters.registry import get_default_registry
from ctxbench.runtime.models import RuntimeRequest
from ctxbench.runtime.runtime import ProvisioningRuntime


def resolve_adaptive_dataset(dataset: dict[str, Any]):
    provenance = DatasetProvenance.model_validate(dataset)
    try:
        return get_default_registry().resolve(provenance)
    except AdapterUnavailableError:
        if provenance.materialized_path:
            return LocalDatasetPackage.from_dataset(provenance)
        raise


def invoke_adaptive_execution(execution_request, session, *, dataset, trace_options: dict[str, Any]):
    payload = execution_request.payload
    if not isinstance(payload, dict):
        raise ValueError("adaptive execution payload must be an object")
    runtime_payload = payload.get("runtimeRequest")
    result_metadata = payload.get("resultMetadata")
    if not isinstance(runtime_payload, dict) or not isinstance(result_metadata, dict):
        raise ValueError("adaptive execution payload requires runtimeRequest and resultMetadata objects")
    runtime_request = _runtime_request(runtime_payload, execution_request, result_metadata)
    execution = ProvisioningRuntime(session.resource, dataset).execute(runtime_request)
    ai_result = execution.ai_result
    answer = ai_result.answer or ""
    status = "error" if ai_result.error or not answer.strip() else "success"
    result_metadata = dict(result_metadata)
    config = runtime_request.configuration
    provisioning = {
        "configurationId": result_metadata.get("configurationId", execution_request.candidate_id),
        "candidateId": execution_request.candidate_id,
        "strategy": config.strategy,
        "representation": config.representation,
        "surface": config.surface,
    }
    metadata = {
        "canonicalId": execution_request.correlation_id,
        "taskId": execution_request.task_id,
        "instanceId": execution_request.instance_id,
        "provider": runtime_request.provider,
        "modelId": result_metadata.get("modelId", runtime_request.model_name),
        "modelName": runtime_request.model_name,
        "repeatIndex": 1,
        "taskTags": result_metadata.get("taskTags", []),
        "validationType": result_metadata.get("validationType"),
        "validationConfig": result_metadata.get("validationConfig", {}),
        "parameters": result_metadata.get("parameters", runtime_request.params),
        "surfaceSpec": runtime_request.surface_spec,
        **provisioning,
    }
    trace_metrics = ai_result.trace.get("metrics", {}) if isinstance(ai_result.trace, dict) else {}
    if not isinstance(trace_metrics, dict):
        trace_metrics = {}
    metrics = dict(trace_metrics)
    metrics.update({
        "totalDurationMs": execution.duration_ms,
        "totalDurationProvenance": "measured",
        "totalTokensProvenance": metrics.get("totalTokensProvenance", "unavailable"),
        "usageCompleteness": metrics.get("usageCompleteness", "unavailable"),
    })
    return {
        "experimentId": result_metadata.get("experimentId", execution_request.experiment_id),
        "dataset": result_metadata.get("dataset", {}),
        "taskId": execution_request.task_id,
        "taskStatement": runtime_request.task,
        "taskTags": result_metadata.get("taskTags", []),
        "validationType": result_metadata.get("validationType"),
        "validationConfig": result_metadata.get("validationConfig", {}),
        "contextBlocks": result_metadata.get("contextBlocks", []),
        "parameters": result_metadata.get("parameters", runtime_request.params),
        "instanceId": execution_request.instance_id,
        "provider": runtime_request.provider,
        "modelId": result_metadata.get("modelId", runtime_request.model_name),
        "model": runtime_request.model_name,
        **provisioning,
        "repeatIndex": 1,
        "surfaceSpec": runtime_request.surface_spec,
        "metadata": metadata,
        "status": status,
        "response": answer,
        "errorMessage": ai_result.error or ("Model returned empty answer" if not answer.strip() else None),
        "timing": {
            "startedAt": execution.started_at,
            "finishedAt": execution.finished_at,
            "durationMs": execution.duration_ms,
        },
        "usage": ai_result.usage,
        "metricsSummary": metrics,
        # Recorded even when the trace is not kept, so a failure stays classifiable.
        "failureCategory": _trace_failure_category(ai_result.trace) if status != "success" else None,
        "trace": ai_result.trace if trace_options.get("enabled", False) else {},
    }


def _trace_failure_category(trace: Any) -> str | None:
    """Category the engine or strategy wrote on the last trace error event, if any."""
    events = trace.get("events") if isinstance(trace, dict) else None
    for event in reversed(events if isinstance(events, list) else []):
        if isinstance(event, dict) and event.get("type") == "error":
            metadata = event.get("metadata")
            category = metadata.get("category") if isinstance(metadata, dict) else None
            return category if isinstance(category, str) and category else None
    return None


def _runtime_request(payload: dict[str, Any], execution_request, result_metadata: dict[str, Any]) -> RuntimeRequest:
    required = {"task", "provider", "model_name", "configuration", "surface_spec", "params"}
    if required - set(payload):
        raise ValueError(f"runtimeRequest is missing fields: {', '.join(sorted(required - set(payload)))}")
    config = ProvisioningConfiguration.model_validate(payload["configuration"])
    if config.strategy not in {"inline", "local_function", "local_mcp", "remote_mcp"}:
        raise ValueError("adaptive runtimeRequest uses an unsupported strategy")
    if execution_request.candidate_id != result_metadata.get("candidateId", execution_request.candidate_id):
        raise ValueError("resultMetadata candidateId differs from selected candidate")
    return RuntimeRequest(
        task=str(payload["task"]),
        task_id=execution_request.task_id,
        instance_id=execution_request.instance_id,
        provider=str(payload["provider"]),
        model_name=str(payload["model_name"]),
        configuration=config,
        surface_spec=dict(payload["surface_spec"]),
        params=dict(payload["params"]),
        metadata=dict(payload.get("metadata", {})),
        cache_model_name=payload.get("cache_model_name"),
    )
