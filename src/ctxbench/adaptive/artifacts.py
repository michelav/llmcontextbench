"""Versioned adaptive plan and artifact serialization."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any

from ctxbench.adaptive.plan import (
    ADAPTIVE_PLAN_VERSION, AdaptivePlan, CandidateSpec, PlannedRequest, WindowSpec,
)
from ctxbench.adaptive.policy import PolicyReference
from ctxbench.core.fingerprint import (
    file_digest, tree_digest,
)
from ctxbench.dataset.provenance import DatasetProvenance
from ctxbench.util.fs import load_json, write_json


ADAPTIVE_ARTIFACT_VERSION = 3
ADAPTIVE_MANIFEST_VERSION = 3


def adaptive_plan_payload(plan: AdaptivePlan) -> dict[str, Any]:
    """Return the canonical JSON form of an adaptive plan v4."""
    policy = plan.policy
    return {
        "adaptivePlanVersion": ADAPTIVE_PLAN_VERSION,
        "workflowId": plan.workflow_id,
        "seed": plan.seed,
        "labels": dict(plan.labels),
        "candidates": [{
            "candidateId": row.candidate_id, "labels": dict(row.labels), "modelId": row.model_id,
            "provider": row.provider, "modelName": row.model_name, "modelParams": _jsonable(row.model_params),
            "configurationId": row.configuration_id, "configuration": dict(row.configuration),
            "surfaceSpec": _jsonable(row.surface_spec), "executionOptions": _jsonable(row.execution_options),
        } for row in plan.candidates],
        "requests": [{
            "requestId": row.request_id, "sequenceIndex": row.sequence_index, "taskId": row.task_id,
            "instanceId": row.instance_id, "taskStatement": row.task_statement,
            "taskTemplate": row.task_template, "parameters": _jsonable(row.parameters),
            "taskTags": list(row.task_tags), "validationType": row.validation_type,
            "validationConfig": _jsonable(row.validation_config), "contextBlocks": list(row.context_blocks),
            "labels": dict(row.labels),
        } for row in plan.requests],
        "workloadSource": _jsonable(plan.workload_source),
        "policy": {"ref": policy.ref, "id": policy.policy_id, "version": policy.version,
                   "params": _jsonable(policy.params), "sourceDigest": policy.source_digest,
                   "sources": list(policy.sources)},
        "window": {"requests": plan.window.requests, "mode": plan.window.mode},
        "signals": _jsonable(plan.signals), "acceptance": _jsonable(plan.acceptance),
        "goals": _jsonable(plan.goals), "disturbances": _jsonable(plan.disturbances),
        "evaluation": _jsonable(plan.evaluation), "trace": _jsonable(plan.trace),
        "allowMixedModels": plan.allow_mixed_models,
        "provenance": _jsonable(plan.provenance),
    }


def adaptive_plan_from_payload(payload: Any, *, dataset: Any = None,
                               resolved_definition: dict[str, Any] | None = None) -> AdaptivePlan:
    if not isinstance(payload, dict):
        raise ValueError("Adaptive plan must be a JSON object")
    version = payload.get("adaptivePlanVersion")
    if version != ADAPTIVE_PLAN_VERSION:
        raise ValueError(
            f"Unsupported adaptive plan version {version!r}; create a fresh adaptive plan "
            f"with version {ADAPTIVE_PLAN_VERSION}."
        )
    required = {"adaptivePlanVersion", "workflowId", "seed", "labels", "candidates", "requests",
                "workloadSource", "policy", "window", "signals", "acceptance", "goals",
                "disturbances", "evaluation", "trace", "allowMixedModels", "provenance"}
    _exact_keys(payload, required, "adaptive plan")
    provenance = payload["provenance"]
    _exact_keys(provenance, {"dataset", "implementation"}, "plan provenance")
    _exact_keys(provenance["dataset"], {"digest"}, "dataset provenance")
    _exact_keys(provenance["implementation"], {"digest", "dependencies"}, "implementation provenance")
    if (not isinstance(provenance["dataset"]["digest"], str)
            or not provenance["dataset"]["digest"]
            or not isinstance(provenance["implementation"]["digest"], str)
            or not provenance["implementation"]["digest"]
            or not isinstance(provenance["implementation"]["dependencies"], dict)):
        raise ValueError("Invalid adaptive plan provenance")
    policy_payload = payload["policy"]
    _exact_keys(policy_payload, {"ref", "id", "version", "params", "sourceDigest", "sources"}, "policy")
    policy = PolicyReference(
        ref=policy_payload["ref"], params=policy_payload["params"], policy_id=policy_payload["id"],
        version=policy_payload["version"], source_digest=policy_payload["sourceDigest"],
        sources=tuple(policy_payload["sources"]),
    )
    candidates = []
    for row in payload["candidates"]:
        _exact_keys(row, {"candidateId", "labels", "modelId", "provider", "modelName", "modelParams",
                          "configurationId", "configuration", "surfaceSpec", "executionOptions"}, "candidate")
        candidates.append(CandidateSpec(
            row["candidateId"], row["modelId"], row["provider"], row["modelName"], row["modelParams"],
            row["configurationId"], row["configuration"], row["surfaceSpec"], row["executionOptions"], row["labels"],
        ))
    requests = []
    for row in payload["requests"]:
        _exact_keys(row, {"requestId", "sequenceIndex", "taskId", "instanceId", "taskStatement", "taskTemplate",
                          "parameters", "taskTags", "validationType", "validationConfig", "contextBlocks", "labels"}, "request")
        requests.append(PlannedRequest(
            row["requestId"], row["sequenceIndex"], row["taskId"], row["instanceId"], row["taskStatement"],
            row["taskTemplate"], row["parameters"], tuple(row["taskTags"]), row["validationType"],
            row["validationConfig"], tuple(row["contextBlocks"]), row["labels"],
        ))
    window = payload["window"]
    _exact_keys(window, {"requests", "mode"}, "window")
    return AdaptivePlan(
        workflow_id=payload["workflowId"], seed=payload["seed"], labels=payload["labels"],
        candidates=tuple(candidates), requests=tuple(requests), workload_source=payload["workloadSource"],
        policy=policy, window=WindowSpec(window["requests"], window["mode"]),
        acceptance=payload["acceptance"], signals=tuple(payload["signals"]), goals=tuple(payload["goals"]),
        disturbances=tuple(payload["disturbances"]), evaluation=payload["evaluation"], trace=payload["trace"],
        allow_mixed_models=payload["allowMixedModels"], dataset=DatasetProvenance.model_validate(dataset)
        if dataset is not None else None, provenance=payload["provenance"],
        resolved_definition=resolved_definition or {},
    )


def write_adaptive_artifacts(artifact_root: str | Path, plan: AdaptivePlan, *,
                             dataset: dict[str, Any] | None = None,
                             evaluation: dict[str, Any] | None = None,
                             trace: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(artifact_root)
    root.mkdir(parents=True, exist_ok=True)
    plan_payload = adaptive_plan_payload(plan)
    plan_path = root / "adaptive-plan.json"
    resolved_path = root / "resolved.json"
    write_json(plan_path, plan_payload)
    write_json(resolved_path, _jsonable(plan.resolved_definition))
    provenance = dataset or (plan.dataset.model_dump(mode="json") if plan.dataset else {})
    fingerprint = file_digest(plan_path)
    if fingerprint != _plan_fingerprint(plan_payload):
        raise ValueError("Adaptive plan serialization is not stable; create a fresh adaptive plan.")
    manifest = {
        "schemaVersion": ADAPTIVE_MANIFEST_VERSION,
        "workflowKind": "adaptive",
        "adaptiveArtifactVersion": ADAPTIVE_ARTIFACT_VERSION,
        "adaptivePlanVersion": ADAPTIVE_PLAN_VERSION,
        "executionRecordVersion": 1,
        "experimentId": plan.workflow_id,
        "workflowId": plan.workflow_id,
        "executionFingerprint": fingerprint,
        "dataset": provenance,
        "evaluation": evaluation or dict(plan.evaluation) or {"enabled": False, "judges": []},
        "trace": trace or dict(plan.trace) or {"enabled": False, "writeFiles": False},
        "labels": dict(plan.labels),
        "privileged": any(bool(row.get("usesReferenceData")) for row in plan.signals),
        "seed": plan.seed,
        "mixedModels": plan.allow_mixed_models,
    }
    write_json(root / "manifest.json", manifest)
    return manifest


def validate_workflow_manifest(root: str | Path, *, execution: bool = False,
                               plugin_paths=()) -> dict[str, Any]:
    """Validate an adaptive manifest and frozen plan; never dispatches other workflow kinds."""
    artifact_root = Path(root)
    manifest_path = artifact_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Unsupported adaptive artifact contract; create a fresh adaptive plan.")
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("workflowKind") != "adaptive":
        raise ValueError(f"Expected an adaptive manifest: {manifest_path}")
    if (manifest.get("schemaVersion") != ADAPTIVE_MANIFEST_VERSION
            or manifest.get("adaptiveArtifactVersion") != ADAPTIVE_ARTIFACT_VERSION
            or manifest.get("adaptivePlanVersion") != ADAPTIVE_PLAN_VERSION
            or manifest.get("executionRecordVersion") != 1):
        raise ValueError("Unsupported adaptive artifact contract; create a fresh adaptive plan.")
    required = {"schemaVersion", "workflowKind", "adaptiveArtifactVersion", "adaptivePlanVersion",
                "executionRecordVersion", "experimentId", "workflowId", "executionFingerprint",
                "dataset", "evaluation", "trace", "labels", "privileged", "seed", "mixedModels"}
    _exact_keys(manifest, required, "adaptive manifest")
    plan_payload = load_json(artifact_root / "adaptive-plan.json")
    plan = adaptive_plan_from_payload(plan_payload, dataset=manifest["dataset"])
    plan_path = artifact_root / "adaptive-plan.json"
    if (file_digest(plan_path) != manifest["executionFingerprint"]
            or plan.workflow_id != manifest["workflowId"]
            or manifest["experimentId"] != plan.workflow_id):
        raise ValueError("Adaptive manifest does not match its frozen adaptive plan.")
    if execution:
        expected_dataset_digest = plan.provenance.get("dataset", {}).get("digest")
        actual_dataset_digest = _dataset_digest(manifest["dataset"])
        if not expected_dataset_digest or actual_dataset_digest != expected_dataset_digest:
            raise ValueError("Adaptive dataset changed since planning; create a fresh adaptive plan.")
        from ctxbench.adaptive.policy import verify_policy
        verify_policy(plan.policy, plugin_paths=plugin_paths)
    return manifest


def adaptive_plan_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "required": ["adaptivePlanVersion", "workflowId", "seed", "labels", "candidates", "requests",
                         "workloadSource", "policy", "window", "signals", "acceptance", "goals",
                         "disturbances", "evaluation", "trace", "allowMixedModels", "provenance"],
            "properties": {"adaptivePlanVersion": {"const": ADAPTIVE_PLAN_VERSION}}}


def _exact_keys(value: Any, expected: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"Invalid {name} fields; expected {', '.join(sorted(expected))}")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    raise TypeError(f"Adaptive plan contains non-JSON value: {type(value).__name__}")


def _plan_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _dataset_digest(provenance: dict[str, Any]) -> str | None:
    dataset_root = provenance.get("materializedPath") or provenance.get("materialized_path")
    if dataset_root and Path(dataset_root).is_dir():
        return tree_digest(Path(dataset_root))
    return provenance.get("contentHash") or provenance.get("content_hash")


__all__ = ["ADAPTIVE_ARTIFACT_VERSION", "ADAPTIVE_MANIFEST_VERSION", "adaptive_plan_payload",
           "adaptive_plan_from_payload", "adaptive_plan_schema", "validate_workflow_manifest",
           "write_adaptive_artifacts"]
