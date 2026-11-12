"""Versioned adaptive plan and artifact manifest contract."""
from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any
from copy import deepcopy

from ctxbench.dataset.capabilities import (
    FeatureCapability,
    FeaturePartitionCapability,
    RequestFeatureSchema,
)
from ctxbench.execution.service import ExecutionRequest
from ctxbench.util.fs import load_json, write_json

from .calibration_contract import (
    CalibrationArtifact,
    CalibrationEstimate,
    CalibrationProvenance,
    CalibrationQualitySource,
)
from .estimator import EstimatorDefinition, FeaturePartitionKey
from .sensors import SensorClass
from .types import (
    Candidate,
    ContextFit,
    Estimate,
    PerformanceEstimate,
    Provenance,
    RequestFeatures,
    SizeBin,
)
from .workflow import (
    ADAPTIVE_PLAN_VERSION,
    AdaptiveCandidateInvocation,
    AdaptivePlan,
    AdaptiveWorkloadRequest,
    AdaptiveWorkflowPolicy,
    QualitySLO,
)


ADAPTIVE_ARTIFACT_VERSION = 1


def adaptive_plan_payload(plan: AdaptivePlan) -> dict[str, Any]:
    """Return the canonical JSON-compatible v2 plan representation."""
    return {
        "schemaVersion": ADAPTIVE_PLAN_VERSION,
        "workflowId": plan.workflow_id,
        "executionFingerprint": plan.execution_fingerprint,
        "datasetId": plan.dataset_id,
        "datasetVersion": plan.dataset_version,
        "candidateCatalogFingerprint": plan.candidate_catalog_fingerprint,
        "featureSchema": _jsonable(plan.feature_schema),
        "policy": _jsonable(plan.policy),
        "estimator": _jsonable(plan.estimator_definition),
        "calibration": _jsonable(plan.calibration),
        "candidateCatalog": list(plan.candidate_catalog),
        "requests": [
            {
                "requestId": request.request_id,
                "sequenceIndex": request.sequence_index,
                "taskId": request.task_id,
                "instanceId": request.instance_id,
                "features": _jsonable(request.features),
                "featureValues": dict(request.feature_values),
                "candidateOrder": list(request.candidate_order),
                "candidates": {
                    candidate_id: {
                        "candidate": _jsonable(invocation.candidate),
                        "execution": _jsonable(invocation.execution),
                    }
                    for candidate_id, invocation in request.candidates.items()
                },
            }
            for request in plan.requests
        ],
    }


def adaptive_plan_from_payload(payload: Any) -> AdaptivePlan:
    """Validate and restore a fresh v2 plan. No v1 migration is attempted."""
    if not isinstance(payload, dict):
        raise ValueError("Adaptive plan must be a JSON object")
    version = payload.get("schemaVersion")
    if version == 1:
        raise ValueError(
            "Adaptive plan schemaVersion 1 is not supported or migrated. Create a fresh adaptive plan."
        )
    required = {
        "schemaVersion", "workflowId", "executionFingerprint", "featureSchema", "policy",
        "estimator", "candidateCatalog", "requests",
    }
    if version != ADAPTIVE_PLAN_VERSION:
        raise ValueError(f"Unsupported adaptive plan schemaVersion {version!r}; expected {ADAPTIVE_PLAN_VERSION}")
    from jsonschema import Draft202012Validator
    Draft202012Validator(adaptive_plan_schema()).validate(payload)
    if required - set(payload):
        raise ValueError(f"Adaptive plan is missing fields: {', '.join(sorted(required - set(payload)))}")
    allowed = required | {"datasetId", "datasetVersion", "candidateCatalogFingerprint", "calibration"}
    if set(payload) - allowed:
        raise ValueError(f"Adaptive plan has unknown fields: {', '.join(sorted(set(payload) - allowed))}")
    try:
        feature_payload = payload["featureSchema"]
        _require_keys(feature_payload, {"schema_id", "version", "features"},
                      {"schema_id", "version", "features", "partition_keys", "partitions", "missing_partition_policy"},
                      "featureSchema")
        if any(not isinstance(item, dict) for item in feature_payload["features"]):
            raise ValueError("featureSchema.features entries must be objects")
        features = tuple(FeatureCapability(**item) for item in feature_payload["features"])
        if any(not isinstance(item, dict) for item in feature_payload.get("partitions", [])):
            raise ValueError("featureSchema.partitions entries must be objects")
        partitions = tuple(FeaturePartitionCapability(**item) for item in feature_payload.get("partitions", []))
        feature_schema = RequestFeatureSchema(
            schema_id=feature_payload["schema_id"], version=feature_payload["version"],
            features=features, partition_keys=tuple(feature_payload.get("partition_keys", [])),
            partitions=partitions,
            missing_partition_policy=feature_payload.get("missing_partition_policy", "unpartitioned"),
        )
        policy_payload = payload["policy"]
        _require_keys(policy_payload, set(), {
            "quality_slos", "latency_limit_ms", "token_limit", "minimum_response_length",
            "token_budget", "best_effort_admission", "selection_metric",
        }, "policy")
        if any(not isinstance(item, dict) for item in policy_payload.get("quality_slos", [])):
            raise ValueError("policy.quality_slos entries must be objects")
        _require_keys(payload["estimator"],
                      {"estimator_id", "version", "window_size", "minimum_observations", "accepted_status"},
                      {"estimator_id", "version", "window_size", "minimum_observations", "accepted_status"},
                      "estimator")
        policy = AdaptiveWorkflowPolicy(
            quality_slos=tuple(QualitySLO(**row) for row in policy_payload.get("quality_slos", [])),
            latency_limit_ms=policy_payload.get("latency_limit_ms"),
            token_limit=policy_payload.get("token_limit"),
            minimum_response_length=policy_payload.get("minimum_response_length", 0),
            token_budget=policy_payload.get("token_budget"),
            best_effort_admission=policy_payload.get("best_effort_admission", False),
            selection_metric=policy_payload.get("selection_metric", "declared_order"),
        )
        estimator = EstimatorDefinition(**payload["estimator"])
        requests = tuple(_request_from_payload(item) for item in payload["requests"])
        calibration = _calibration_from_payload(payload.get("calibration"))
        return AdaptivePlan(
            workflow_id=payload["workflowId"],
            execution_fingerprint=payload["executionFingerprint"],
            feature_schema=feature_schema,
            policy=policy,
            requests=requests,
            candidate_catalog=tuple(payload["candidateCatalog"]),
            schema_version=version,
            dataset_id=payload.get("datasetId"),
            dataset_version=payload.get("datasetVersion"),
            candidate_catalog_fingerprint=payload.get("candidateCatalogFingerprint"),
            estimator_definition=estimator,
            calibration=calibration,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid adaptive plan: {exc}") from exc


def write_adaptive_artifacts(
    root: str | Path,
    plan: AdaptivePlan,
    *,
    dataset: dict[str, Any],
    evaluation: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_root = Path(root)
    _validate_dataset_metadata(dataset)
    if ((plan.dataset_id and plan.dataset_id != dataset["id"])
            or (plan.dataset_version and plan.dataset_version != dataset["version"])):
        raise ValueError("Adaptive manifest dataset differs from frozen plan provenance")
    _validate_postprocess_metadata(evaluation or {"enabled": False, "judges": []}, trace or {"enabled": False, "writeFiles": False})
    artifact_root.mkdir(parents=True, exist_ok=True)
    payload = adaptive_plan_payload(plan)
    plan_path = artifact_root / "adaptive-plan.json"
    write_json(plan_path, payload)
    manifest = {
        "schemaVersion": 1,
        "workflowKind": "adaptive",
        "adaptiveArtifactVersion": ADAPTIVE_ARTIFACT_VERSION,
        "adaptivePlanVersion": ADAPTIVE_PLAN_VERSION,
        "executionRecordVersion": 1,
        "experimentId": plan.workflow_id,
        "workflowId": plan.workflow_id,
        "executionFingerprint": plan.execution_fingerprint,
        "planDigest": _digest(payload),
        "dataset": dataset,
        "evaluation": evaluation or {"enabled": False, "judges": []},
        "trace": trace or {"enabled": False, "writeFiles": False},
    }
    write_json(artifact_root / "manifest.json", manifest)
    return manifest


def validate_workflow_manifest(root: str | Path) -> dict[str, Any]:
    """Dispatch manifest validation without forcing adaptive artifacts through benchmark schemas."""
    artifact_root = Path(root)
    manifest_path = artifact_root / "manifest.json"
    if not manifest_path.exists():
        from ctxbench.benchmark.provisioning import validate_manifest
        return validate_manifest(artifact_root)
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError(f"Invalid manifest: {manifest_path}")
    if manifest.get("workflowKind") != "adaptive":
        from ctxbench.benchmark.provisioning import validate_manifest
        return validate_manifest(artifact_root)
    if (type(manifest.get("schemaVersion")) is not int or manifest.get("schemaVersion") != 1
            or type(manifest.get("adaptiveArtifactVersion")) is not int
            or manifest.get("adaptiveArtifactVersion") != ADAPTIVE_ARTIFACT_VERSION
            or type(manifest.get("adaptivePlanVersion")) is not int
            or manifest.get("adaptivePlanVersion") != ADAPTIVE_PLAN_VERSION
            or type(manifest.get("executionRecordVersion")) is not int
            or manifest.get("executionRecordVersion") != 1):
        raise ValueError("Unsupported adaptive artifact contract; create a fresh adaptive plan.")
    _require_keys(manifest, {
        "schemaVersion", "workflowKind", "adaptiveArtifactVersion", "adaptivePlanVersion",
        "executionRecordVersion", "experimentId", "workflowId", "executionFingerprint",
        "planDigest", "dataset", "evaluation", "trace",
    }, {
        "schemaVersion", "workflowKind", "adaptiveArtifactVersion", "adaptivePlanVersion",
        "executionRecordVersion", "experimentId", "workflowId", "executionFingerprint",
        "planDigest", "dataset", "evaluation", "trace",
    }, "adaptive manifest")
    _validate_dataset_metadata(manifest["dataset"])
    _validate_postprocess_metadata(manifest["evaluation"], manifest["trace"])
    plan_path = artifact_root / "adaptive-plan.json"
    plan = adaptive_plan_from_payload(load_json(plan_path))
    if (plan.workflow_id != manifest.get("workflowId")
            or manifest.get("experimentId") != plan.workflow_id
            or plan.execution_fingerprint != manifest.get("executionFingerprint")
            or (plan.dataset_id and plan.dataset_id != manifest["dataset"].get("id"))
            or (plan.dataset_version and plan.dataset_version != manifest["dataset"].get("version"))
            or _digest(adaptive_plan_payload(plan)) != manifest.get("planDigest")):
        raise ValueError("Adaptive manifest does not match its frozen adaptive plan.")
    return manifest


def _request_from_payload(payload: dict[str, Any]) -> AdaptiveWorkloadRequest:
    _require_keys(payload, {"requestId", "sequenceIndex", "taskId", "instanceId", "features",
                            "featureValues", "candidateOrder", "candidates"},
                  {"requestId", "sequenceIndex", "taskId", "instanceId", "features",
                   "featureValues", "candidateOrder", "candidates"}, "request")
    feature_payload = payload["features"]
    _require_keys(feature_payload, {"sequence_index", "context_bytes"},
                  {"sequence_index", "context_bytes", "size_bin"}, "request.features")
    features = RequestFeatures(
        sequence_index=feature_payload["sequence_index"],
        context_bytes=feature_payload["context_bytes"],
        size_bin=SizeBin(feature_payload["size_bin"]) if feature_payload.get("size_bin") else None,
    )
    invocations = {}
    for candidate_id, item in payload["candidates"].items():
        _require_keys(item, {"candidate", "execution"}, {"candidate", "execution"}, "request candidate")
        candidate_payload = item["candidate"]
        _require_keys(candidate_payload, {"configuration_id", "executable", "context_fit"},
                      {"configuration_id", "executable", "context_fit"}, "candidate")
        _require_keys(candidate_payload["context_fit"],
                      {"input_tokens", "output_reservation", "context_limit", "provenance"},
                      {"input_tokens", "output_reservation", "context_limit", "provenance"}, "candidate.context_fit")
        _require_keys(item["execution"], {field.name for field in fields(ExecutionRequest)},
                      {field.name for field in fields(ExecutionRequest)}, "execution request")
        fit = ContextFit(**candidate_payload["context_fit"])
        candidate = Candidate(
            configuration_id=candidate_payload["configuration_id"],
            executable=candidate_payload["executable"],
            context_fit=fit,
        )
        execution = ExecutionRequest(**item["execution"])
        invocations[candidate_id] = AdaptiveCandidateInvocation(candidate, execution)
    return AdaptiveWorkloadRequest(
        request_id=payload["requestId"], sequence_index=payload["sequenceIndex"],
        task_id=payload["taskId"], instance_id=payload["instanceId"],
        features=features, feature_values=payload["featureValues"],
        candidate_order=tuple(payload["candidateOrder"]), candidates=invocations,
    )


def _calibration_from_payload(payload: Any) -> CalibrationArtifact | None:
    if payload is None:
        return None
    provenance = payload["provenance"]
    estimator = EstimatorDefinition(**provenance["estimator"])
    quality_sources = tuple(CalibrationQualitySource(
        metric_id=row["metric_id"], assessor_id=row["assessor_id"],
        sensor_class=SensorClass(row["sensor_class"]), provenance=Provenance(row["provenance"]),
    ) for row in provenance.get("quality_sources", []))
    source = CalibrationProvenance(
        source_run_id=provenance["source_run_id"],
        source_artifact_fingerprint=provenance["source_artifact_fingerprint"],
        dataset_id=provenance["dataset_id"], dataset_version=provenance["dataset_version"],
        candidate_catalog_fingerprint=provenance["candidate_catalog_fingerprint"],
        feature_schema_id=provenance["feature_schema_id"],
        feature_schema_version=provenance["feature_schema_version"], estimator=estimator,
        source_request_ids=tuple(provenance["source_request_ids"]), quality_sources=quality_sources,
        schema_version=provenance.get("schema_version", 1),
    )
    estimates = []
    for row in payload["estimates"]:
        partition_payload = row["partition"]
        partition = FeaturePartitionKey(
            partition_payload["schema_id"], partition_payload["schema_version"],
            tuple(tuple(item) for item in partition_payload["values"]),
        )
        estimates.append(CalibrationEstimate(
            configuration_id=row["configuration_id"], partition=partition,
            estimate=_performance_from_payload(row["estimate"]),
        ))
    return CalibrationArtifact(source, tuple(estimates))


def _performance_from_payload(payload: dict[str, Any]) -> PerformanceEstimate:
    def estimate(field: str) -> Estimate:
        item = payload[field]
        return Estimate(
            item.get("value"), Provenance(item["provenance"]), item.get("observation_count", 0),
            tuple(Provenance(value) for value in item.get("source_provenance", [])),
        )
    return PerformanceEstimate(estimate("latency_ms"), estimate("total_tokens"))


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


def _validate_dataset_metadata(dataset: Any) -> None:
    required = {"id", "version"}
    allowed = required | {"origin", "resolvedRevision", "contentHash", "materializedPath"}
    _require_keys(dataset, required, allowed, "dataset")
    if any(not isinstance(dataset.get(name), str) or not dataset[name] for name in required):
        raise ValueError("Adaptive manifest dataset id and version must be nonempty strings")


def _validate_postprocess_metadata(evaluation: Any, trace: Any) -> None:
    if not isinstance(evaluation, dict) or type(evaluation.get("enabled")) is not bool:
        raise ValueError("Adaptive manifest evaluation must declare an enabled boolean")
    if set(evaluation) - {"enabled", "judges"}:
        raise ValueError(f"Adaptive evaluation has unknown fields: {', '.join(sorted(set(evaluation) - {'enabled', 'judges'}))}")
    judges = evaluation.get("judges", [])
    if not isinstance(judges, list) or any(not isinstance(judge, dict) for judge in judges):
        raise ValueError("Adaptive manifest evaluation judges must be objects")
    if not isinstance(trace, dict):
        raise ValueError("Adaptive manifest trace settings must be an object")
    allowed_trace = {"enabled", "writeFiles", "save_raw_response", "save_tool_calls", "save_usage", "save_errors"}
    unknown_trace = set(trace) - allowed_trace
    if unknown_trace:
        raise ValueError(f"Adaptive trace has unknown fields: {', '.join(sorted(unknown_trace))}")
    if any(type(value) is not bool for value in trace.values()):
        raise ValueError("Adaptive trace settings must be booleans")


def _require_keys(payload: Any, required: set[str], allowed: set[str], label: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    missing = required - set(payload)
    unknown = set(payload) - allowed
    if missing:
        raise ValueError(f"{label} is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")


def adaptive_plan_schema() -> dict[str, Any]:
    """JSON Schema for the persisted adaptive plan contract (schemaVersion 2)."""
    scalar = {"type": ["string", "number", "integer", "boolean", "null"]}
    execution = {
        "type": "object", "additionalProperties": False,
        "required": ["execution_id", "workflow_id", "correlation_id", "experiment_id",
                     "execution_fingerprint", "task_id", "instance_id", "candidate_id", "payload", "trial_id"],
        "properties": {
            "execution_id": {"type": "string", "minLength": 1},
            "workflow_id": {"type": "string", "minLength": 1},
            "correlation_id": {"type": "string", "minLength": 1},
            "experiment_id": {"type": "string", "minLength": 1},
            "execution_fingerprint": {"type": "string", "minLength": 1},
            "task_id": {"type": "string", "minLength": 1},
            "instance_id": {"type": "string", "minLength": 1},
            "candidate_id": {"type": ["string", "null"]},
            "payload": {}, "trial_id": {"type": ["string", "null"]},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": ["schemaVersion", "workflowId", "executionFingerprint", "featureSchema",
                     "policy", "estimator", "candidateCatalog", "requests"],
        "properties": {
            "schemaVersion": {"const": ADAPTIVE_PLAN_VERSION},
            "workflowId": {"type": "string", "minLength": 1},
            "executionFingerprint": {"type": "string", "minLength": 1},
            "datasetId": {"type": ["string", "null"]},
            "datasetVersion": {"type": ["string", "null"]},
            "candidateCatalogFingerprint": {"type": ["string", "null"]},
            "featureSchema": {
                "type": "object", "additionalProperties": False,
                "required": ["schema_id", "version", "features", "partition_keys", "partitions", "missing_partition_policy"],
                "properties": {
                    "schema_id": {"type": "string", "minLength": 1},
                    "version": {"type": "string", "minLength": 1},
                    "features": {"type": "array", "items": {"type": "object"}},
                    "partition_keys": {"type": "array", "items": {"type": "string"}},
                    "partitions": {"type": "array", "items": {"type": "object"}},
                    "missing_partition_policy": {"enum": ["unpartitioned", "explicit"]},
                },
            },
            "policy": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "quality_slos": {"type": "array", "items": {
                        "type": "object", "additionalProperties": False,
                        "required": ["metric_id", "minimum_value"],
                        "properties": {"metric_id": {"type": "string", "minLength": 1},
                                       "minimum_value": {"type": "number"}},
                    }},
                    "latency_limit_ms": {"type": ["number", "null"], "minimum": 0},
                    "token_limit": {"type": ["integer", "null"], "minimum": 0},
                    "minimum_response_length": {"type": "integer", "minimum": 0},
                    "token_budget": {"type": ["integer", "null"], "minimum": 0},
                    "best_effort_admission": {"type": "boolean"},
                    "selection_metric": {"enum": ["declared_order", "latency", "tokens"]},
                },
            },
            "estimator": {
                "type": "object", "additionalProperties": False,
                "required": ["estimator_id", "version", "window_size", "minimum_observations", "accepted_status"],
                "properties": {
                    "estimator_id": {"type": "string", "minLength": 1},
                    "version": {"type": "string", "minLength": 1},
                    "window_size": {"type": "integer", "minimum": 1},
                    "minimum_observations": {"type": "integer", "minimum": 1},
                    "accepted_status": {"type": "string", "minLength": 1},
                },
            },
            "candidateCatalog": {"type": "array", "minItems": 1, "uniqueItems": True,
                                 "items": {"type": "string", "minLength": 1}},
            "calibration": {"type": ["object", "null"]},
            "requests": {"type": "array", "minItems": 1, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["requestId", "sequenceIndex", "taskId", "instanceId", "features",
                             "featureValues", "candidateOrder", "candidates"],
                "properties": {
                    "requestId": {"type": "string", "minLength": 1},
                    "sequenceIndex": {"type": "integer", "minimum": 1},
                    "taskId": {"type": "string", "minLength": 1},
                    "instanceId": {"type": "string", "minLength": 1},
                    "features": {"type": "object", "additionalProperties": False,
                                 "required": ["sequence_index", "context_bytes"],
                                 "properties": {"sequence_index": {"type": "integer", "minimum": 1},
                                                "context_bytes": {"type": "integer", "minimum": 0},
                                                "size_bin": {"enum": ["small", "medium", "large", None]}}},
                    "featureValues": {"type": "object", "additionalProperties": scalar},
                    "candidateOrder": {"type": "array", "items": {"type": "string"}},
                    "candidates": {"type": "object", "minProperties": 1, "additionalProperties": {
                        "type": "object", "additionalProperties": False,
                        "required": ["candidate", "execution"],
                        "properties": {
                            "candidate": {"type": "object", "additionalProperties": False,
                                          "required": ["configuration_id", "executable", "context_fit"],
                                          "properties": {
                                              "configuration_id": {"type": "string", "minLength": 1},
                                              "executable": {"type": "boolean"},
                                              "context_fit": {"type": "object", "additionalProperties": False,
                                                              "required": ["input_tokens", "output_reservation", "context_limit", "provenance"],
                                                              "properties": {
                                                                  "input_tokens": {"type": "integer", "minimum": 0},
                                                                  "output_reservation": {"type": "integer", "minimum": 0},
                                                                  "context_limit": {"type": "integer", "minimum": 0},
                                                                  "provenance": {"enum": ["derived", "estimated"]},
                                                              }},
                                          }},
                            "execution": execution,
                        },
                    }},
                },
            }},
        },
    }


def adaptive_definition_schema() -> dict[str, Any]:
    """JSON Schema for the CLI's workflowKind=adaptive definition envelope."""
    schema = deepcopy(adaptive_plan_schema())
    schema["required"].extend(["workflowKind", "dataset"])
    schema["properties"].update({
        "workflowKind": {"const": "adaptive"},
        "output": {"type": "string", "minLength": 1},
        "dataset": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "version"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "version": {"type": "string", "minLength": 1},
                "origin": {"type": ["string", "null"]},
                "resolvedRevision": {"type": ["string", "null"]},
                "contentHash": {"type": ["string", "null"]},
                "materializedPath": {"type": ["string", "null"]},
            },
        },
        "evaluation": {
            "type": "object", "additionalProperties": False,
            "required": ["enabled"],
            "properties": {"enabled": {"type": "boolean"},
                           "judges": {"type": "array", "items": {"type": "object"}}},
        },
        "trace": {
            "type": "object", "additionalProperties": False,
            "properties": {key: {"type": "boolean"} for key in (
                "enabled", "writeFiles", "save_raw_response", "save_tool_calls", "save_usage", "save_errors",
            )},
        },
    })
    return schema


def validate_adaptive_definition(payload: Any) -> AdaptivePlan:
    from jsonschema import Draft202012Validator
    Draft202012Validator(adaptive_definition_schema()).validate(payload)
    _validate_dataset_metadata(payload["dataset"])
    _validate_postprocess_metadata(
        payload.get("evaluation", {"enabled": False, "judges": []}),
        payload.get("trace", {"enabled": False, "writeFiles": False}),
    )
    plan_payload = {key: value for key, value in payload.items()
                    if key not in {"workflowKind", "output", "dataset", "evaluation", "trace"}}
    plan = adaptive_plan_from_payload(plan_payload)
    if ((plan.dataset_id and plan.dataset_id != payload["dataset"]["id"])
            or (plan.dataset_version and plan.dataset_version != payload["dataset"]["version"])):
        raise ValueError("Adaptive definition dataset differs from frozen plan provenance.")
    return plan


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
