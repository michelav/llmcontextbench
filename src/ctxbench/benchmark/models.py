from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from ctxbench._compat import BaseModel, Field, ValidationError

MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
VALID_STRATEGY_NAMES = {"inline", "local_function", "local_mcp", "remote_mcp"}


def _model_dump_value(value: Any, mode: str) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode=mode)
    if isinstance(value, list):
        return [_model_dump_value(item, mode) for item in value]
    if isinstance(value, dict):
        return {key: _model_dump_value(item, mode) for key, item in value.items()}
    return value


def _coerce_dataset_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    if "dataset" in payload:
        payload["dataset"] = DatasetProvenance.model_validate(payload["dataset"])
    return payload


class ExperimentDataset(BaseModel):
    root: str | None = None
    id: str | None = None
    version: str | None = None
    origin: str | None = None

    @classmethod
    def model_validate(cls, data: Any) -> "ExperimentDataset":
        if isinstance(data, cls):
            return data
        if isinstance(data, str):
            return cls(root=data)
        if isinstance(data, dict):
            if "root" in data:
                return cls(
                    root=str(data["root"]),
                    id=str(data["id"]) if data.get("id") is not None else None,
                    version=str(data["version"]) if data.get("version") is not None else None,
                    origin=str(data["origin"]) if data.get("origin") is not None else None,
                )
            if "id" in data:
                return cls(
                    root=str(data["root"]) if data.get("root") is not None else None,
                    id=str(data["id"]),
                    version=str(data["version"]) if data.get("version") is not None else None,
                    origin=str(data["origin"]) if data.get("origin") is not None else None,
                )
            legacy_paths = {"tasks", "contexts", "task_instances"}
            if legacy_paths & set(data):
                raise ValidationError(
                    "Experiment dataset must be a dataset directory path. "
                    "Put tasks.json and tasks.instance.json in the dataset root "
                    "and context files in <dataset>/context."
                )
        raise ValidationError(
            "ExperimentDataset requires either a dataset directory path/root or an id/version reference."
        )

    def _validate_model(self) -> None:
        has_root = bool(self.root)
        has_id = bool(self.id)
        if not has_root and not has_id:
            raise ValidationError(
                "ExperimentDataset requires either a dataset directory path/root or an id/version reference."
            )
        if has_id and not self.version:
            raise ValidationError("ExperimentDataset id references require a version.")

    @property
    def tasks(self) -> str:
        if not self.root:
            raise ValueError("Dataset tasks path is only available for local-root datasets.")
        return str(Path(self.root) / "tasks.json")

    @property
    def contexts(self) -> str:
        if not self.root:
            raise ValueError("Dataset contexts path is only available for local-root datasets.")
        return str(Path(self.root) / "context")

    @property
    def task_instances(self) -> str:
        if not self.root:
            raise ValueError("Dataset task_instances path is only available for local-root datasets.")
        return str(Path(self.root) / "tasks.instance.json")


class DatasetProvenance(BaseModel):
    id: str
    version: str
    origin: str | None = None
    resolved_revision: str | None = None
    content_hash: str | None = None
    materialized_path: str | None = None

    @classmethod
    def model_validate(cls, data: Any) -> "DatasetProvenance":
        if isinstance(data, cls):
            return data
        if isinstance(data, ExperimentDataset):
            root = data.root
            inferred_id = data.id or (Path(root).name if root else "local-dataset")
            inferred_version = data.version or "local"
            return cls(
                id=inferred_id,
                version=inferred_version,
                origin=data.origin or root,
                materialized_path=root,
            )
        if isinstance(data, str):
            root = str(Path(data).expanduser())
            return cls(
                id=Path(root).name or "local-dataset",
                version="local",
                origin=root,
                materialized_path=root,
            )
        if isinstance(data, dict):
            payload = dict(data)
            legacy_paths = {"tasks", "contexts", "task_instances"}
            if legacy_paths & set(payload) and "root" not in payload and "id" not in payload:
                raise ValidationError(
                    "Dataset provenance must reference a dataset root or id/version. "
                    "Put tasks.json and tasks.instance.json in the dataset root "
                    "and context files in <dataset>/context."
                )
            if "root" in payload:
                root = str(payload.get("root") or "")
                return cls(
                    id=str(payload.get("id") or (Path(root).name if root else "local-dataset")),
                    version=str(payload.get("version") or "local"),
                    origin=str(payload.get("origin") or root) if (payload.get("origin") or root) else None,
                    resolved_revision=payload.get("resolvedRevision") or payload.get("resolved_revision"),
                    content_hash=payload.get("contentHash") or payload.get("content_hash"),
                    materialized_path=str(
                        payload.get("materializedPath")
                        or payload.get("materialized_path")
                        or root
                    )
                    if (
                        payload.get("materializedPath")
                        or payload.get("materialized_path")
                        or root
                    )
                    else None,
                )
            if "id" in payload:
                return cls(
                    id=str(payload.get("id") or ""),
                    version=str(payload.get("version") or ""),
                    origin=str(payload.get("origin")) if payload.get("origin") is not None else None,
                    resolved_revision=payload.get("resolvedRevision") or payload.get("resolved_revision"),
                    content_hash=payload.get("contentHash") or payload.get("content_hash"),
                    materialized_path=str(payload.get("materializedPath") or payload.get("materialized_path"))
                    if (payload.get("materializedPath") or payload.get("materialized_path")) is not None
                    else None,
                )
        raise ValidationError("DatasetProvenance requires an object input.")

    def model_dump(self, mode: str = "python") -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "origin": self.origin,
            "resolvedRevision": self.resolved_revision,
            "contentHash": self.content_hash,
            "materializedPath": self.materialized_path,
        }

    @property
    def root(self) -> str | None:
        return self.materialized_path or self.origin

    @property
    def tasks(self) -> str:
        if not self.root:
            raise ValueError("Dataset tasks path is unavailable without a local materialized path.")
        return str(Path(self.root) / "tasks.json")

    @property
    def contexts(self) -> str:
        if not self.root:
            raise ValueError("Dataset contexts path is unavailable without a local materialized path.")
        return str(Path(self.root) / "context")

    @property
    def task_instances(self) -> str:
        if not self.root:
            raise ValueError("Dataset task_instances path is unavailable without a local materialized path.")
        return str(Path(self.root) / "tasks.instance.json")


class ModelEntry(BaseModel):
    provider: str
    name: str
    params: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def model_validate(cls, data: Any) -> "ModelEntry":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("ModelEntry requires an object input.")
        return cls(
            provider=str(data.get("provider", "")),
            name=str(data.get("name", "")),
            params=dict(data.get("params") or {}),
        )


class ExperimentParams(BaseModel):
    common: dict[str, Any] = Field(default_factory=dict)
    models: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @classmethod
    def model_validate(cls, data: Any) -> "ExperimentParams":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("ExperimentParams requires an object input.")
        common = data.get("common", {})
        if not isinstance(common, dict):
            raise ValidationError("Experiment params.common must be an object.")
        models = {key: value for key, value in data.items() if key != "common"}
        for model_name, params in models.items():
            if not isinstance(params, dict):
                raise ValidationError(f"Experiment params.{model_name} must be an object.")
        return cls(common=common, models=models)

    def model_dump(self, mode: str = "python") -> dict[str, Any]:
        payload = {"common": _model_dump_value(self.common, mode)}
        for model_name, params in self.models.items():
            payload[model_name] = _model_dump_value(params, mode)
        return payload


class ExperimentExecution(BaseModel):
    repeats: int = 1
    output: str | None = None
    jsonl: str | None = None


class ExperimentScope(BaseModel):
    instances: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)

    @classmethod
    def model_validate(cls, data: Any) -> "ExperimentScope":
        if isinstance(data, cls):
            return data
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ValidationError("ExperimentScope requires an object input.")
        if "questions" in data:
            raise ValidationError("ExperimentScope input must use 'tasks', not 'questions'.")
        task_items = data.get("tasks", [])
        return cls(
            instances=[str(item) for item in data.get("instances", []) if isinstance(item, str)],
            tasks=[str(item) for item in task_items if isinstance(item, str)],
        )


class ExperimentExpansion(BaseModel):
    output: str | None = None
    jsonl: str | None = None


class EvaluationModelConfig(BaseModel):
    provider: str
    model: str
    temperature: float | int | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def model_validate(cls, data: Any) -> "EvaluationModelConfig":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("Evaluation model config requires an object input.")
        params: dict[str, Any] = {}
        raw_params = data.get("params")
        if isinstance(raw_params, dict):
            params.update(raw_params)
        for key, value in data.items():
            if key in {"provider", "model", "temperature", "params"}:
                continue
            params[key] = value
        return cls(
            provider=str(data.get("provider", "")),
            model=str(data.get("model", "")),
            temperature=data.get("temperature"),
            params=params,
        )


class ExperimentEvaluation(BaseModel):
    enabled: bool = False
    output: str | None = None
    jsonl: str | None = None
    judges: list[EvaluationModelConfig] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def model_validate(cls, data: Any) -> "ExperimentEvaluation":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("ExperimentEvaluation requires an object input.")
        config = {
            key: value
            for key, value in data.items()
            if key not in {"enabled", "output", "jsonl", "judges"}
        }
        return cls(
            enabled=bool(data.get("enabled", False)),
            output=data.get("output"),
            jsonl=data.get("jsonl"),
            judges=[
                EvaluationModelConfig.model_validate(item)
                for item in data.get("judges", [])
                if isinstance(item, dict)
            ],
            config=config,
        )


class ExperimentTrace(BaseModel):
    enabled: bool = False
    writeFiles: bool = True
    save_raw_response: bool = False
    save_tool_calls: bool = False
    save_usage: bool = False
    save_errors: bool = False


class ExperimentArtifacts(BaseModel):
    writeJsonl: bool = True
    writeIndividualJson: bool = False


class Experiment(BaseModel):
    id: str
    name: str | None = None
    output: str = "outputs"
    dataset: ExperimentDataset
    scope: ExperimentScope = Field(default_factory=ExperimentScope)
    factors: dict[str, list[Any]]
    models: dict[str, ModelEntry] = Field(default_factory=dict)
    params: ExperimentParams = Field(default_factory=ExperimentParams)
    expansion: ExperimentExpansion = Field(default_factory=ExperimentExpansion)
    evaluation: ExperimentEvaluation = Field(default_factory=ExperimentEvaluation)
    trace: ExperimentTrace = Field(default_factory=ExperimentTrace)
    execution: ExperimentExecution = Field(default_factory=ExperimentExecution)
    artifacts: ExperimentArtifacts = Field(default_factory=ExperimentArtifacts)

    @classmethod
    def model_validate(cls, data: Any) -> "Experiment":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("Experiment requires an object input.")
        payload = dict(data)
        if "dataset" in payload:
            payload["dataset"] = ExperimentDataset.model_validate(payload["dataset"])
        if "scope" in payload:
            payload["scope"] = ExperimentScope.model_validate(payload["scope"])

        # New format: top-level "models" section present
        if "models" in payload and isinstance(payload["models"], dict):
            parsed_models: dict[str, ModelEntry] = {
                k: ModelEntry.model_validate(v)
                for k, v in payload["models"].items()
                if isinstance(v, dict)
            }
            payload["models"] = parsed_models

            # params at root is a flat common dict (no "common" key) → wrap for ExperimentParams
            if "params" in payload and isinstance(payload["params"], dict):
                if "common" not in payload["params"]:
                    payload["params"] = {"common": payload["params"]}

            # Resolve string judge references to EvaluationModelConfig dicts
            if "evaluation" in payload and isinstance(payload["evaluation"], dict):
                judges_raw = payload["evaluation"].get("judges", [])
                resolved_judges: list[Any] = []
                for j in judges_raw:
                    if isinstance(j, str) and j in parsed_models:
                        entry = parsed_models[j]
                        resolved_judges.append({
                            "provider": entry.provider,
                            "model": entry.name,
                            "temperature": entry.params.get("temperature"),
                            "id": j,
                        })
                    elif isinstance(j, dict):
                        resolved_judges.append(j)
                payload["evaluation"] = {**payload["evaluation"], "judges": resolved_judges}

        if "params" in payload:
            payload["params"] = ExperimentParams.model_validate(payload["params"])
        if "expansion" in payload and isinstance(payload["expansion"], dict):
            payload["expansion"] = ExperimentExpansion.model_validate(payload["expansion"])
        if "evaluation" in payload and isinstance(payload["evaluation"], dict):
            payload["evaluation"] = ExperimentEvaluation.model_validate(payload["evaluation"])
        if "trace" in payload and isinstance(payload["trace"], dict):
            payload["trace"] = ExperimentTrace.model_validate(payload["trace"])
        if "execution" in payload and isinstance(payload["execution"], dict):
            payload["execution"] = ExperimentExecution.model_validate(payload["execution"])
        if "artifacts" in payload and isinstance(payload["artifacts"], dict):
            payload["artifacts"] = ExperimentArtifacts.model_validate(payload["artifacts"])
        execution = payload.get("execution")
        execution_output = execution.output if isinstance(execution, ExperimentExecution) else execution.get("output") if isinstance(execution, dict) else None
        if not payload.get("output") and execution_output:
            payload["output"] = execution_output
        experiment = super().model_validate(payload)
        experiment._validate_model()
        return experiment

    def _validate_model(self) -> None:
        required = {"model", "strategy", "format"}
        missing = [name for name in sorted(required) if name not in self.factors]
        if missing:
            raise ValueError(f"Experiment factors missing required keys: {', '.join(missing)}")
        empty = [name for name, values in self.factors.items() if not values]
        if empty:
            raise ValueError(f"Experiment factors must not be empty: {', '.join(sorted(empty))}")
        if self.execution.repeats < 1:
            raise ValueError("Experiment execution.repeats must be >= 1.")
        model_ids: set[str] = set()
        if self.models:
            # New format: factors.model contains string IDs referencing self.models
            for model_ref in self.factors.get("model", []):
                if not isinstance(model_ref, str) or not model_ref.strip():
                    raise ValueError("Experiment factors.model entries must be non-empty strings in new format.")
                if model_ref not in self.models:
                    raise ValueError(f"factors.model references unknown model id: '{model_ref}'.")
                if model_ref in model_ids:
                    raise ValueError(f"Duplicate model id in experiment factors.model: {model_ref}")
                model_ids.add(model_ref)
        else:
            # Old format: factors.model contains objects with provider/name
            for model in self.factors.get("model", []):
                if not isinstance(model, dict):
                    raise ValueError("Experiment factors.model entries must be objects.")
                provider = model.get("provider")
                name = model.get("name")
                if not isinstance(provider, str) or not provider.strip():
                    raise ValueError("Experiment factors.model[].provider must be a non-empty string.")
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("Experiment factors.model[].name must be a non-empty string.")
                raw_model_id = model.get("id")
                model_id = raw_model_id if raw_model_id is not None else name
                if not isinstance(model_id, str) or not model_id.strip():
                    raise ValueError("Experiment factors.model[].id must be a non-empty string when provided.")
                if raw_model_id is not None and not MODEL_ID_PATTERN.match(model_id):
                    raise ValueError("Experiment factors.model[].id must contain only letters, numbers, underscore, dot, or hyphen.")
                if model_id in model_ids:
                    raise ValueError(f"Duplicate model id in experiment factors.model: {model_id}")
                model_ids.add(model_id)
        for factor_name in ("strategy", "format"):
            invalid = [value for value in self.factors.get(factor_name, []) if not isinstance(value, str) or not value.strip()]
            if invalid:
                raise ValueError(f"Experiment factors.{factor_name} entries must be non-empty strings.")
        invalid_strategies = [value for value in self.factors.get("strategy", []) if value not in VALID_STRATEGY_NAMES]
        if invalid_strategies:
            joined = ", ".join(sorted({str(value) for value in invalid_strategies}))
            raise ValueError(f"unknown strategy: {joined}")


class TrialMetadata(BaseModel):
    canonicalId: str
    taskId: str
    instanceId: str
    provider: str
    modelId: str | None = None
    modelName: str | None = None
    strategy: str
    format: str
    repeatIndex: int
    taskTags: list[str] = Field(default_factory=list)
    validationType: str | None = None
    validationConfig: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def model_validate(cls, data: Any) -> "TrialMetadata":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("TrialMetadata requires an object input.")
        payload = dict(data)
        if "questionId" in payload:
            raise ValueError("Public TrialMetadata input must use 'taskId', not 'questionId'.")
        return super().model_validate(payload)


RunMetadata = TrialMetadata


class TrialSpec(BaseModel):
    id: str
    trialId: str
    experimentId: str
    dataset: DatasetProvenance
    experimentPath: str | None = None
    taskId: str
    taskStatement: str = ""
    taskTemplate: str | None = None
    taskTags: list[str] = Field(default_factory=list)
    validationType: str | None = None
    validationConfig: dict[str, Any] = Field(default_factory=dict)
    contextBlocks: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    instanceId: str
    provider: str
    modelId: str | None = None
    modelName: str | None = None
    strategy: str
    format: str
    params: dict[str, Any] = Field(default_factory=dict)
    repeatIndex: int = 1
    outputRoot: str | None = None
    evaluationEnabled: bool = False
    trace: ExperimentTrace = Field(default_factory=ExperimentTrace)
    artifacts: ExperimentArtifacts = Field(default_factory=ExperimentArtifacts)
    metadata: TrialMetadata

    @classmethod
    def model_validate(cls, data: Any) -> "TrialSpec":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("TrialSpec requires an object input.")
        payload = dict(data)
        if "runId" in payload:
            raise ValueError("Public TrialSpec input must use 'trialId', not 'runId'.")
        if "questionId" in payload:
            raise ValueError("Public TrialSpec input must use 'taskId', not 'questionId'.")
        if "question" in payload:
            raise ValueError("Public TrialSpec input must use 'taskStatement', not 'question'.")
        strategy = payload.get("strategy")
        if isinstance(strategy, str) and strategy == "mcp":
            raise ValueError("unknown strategy: mcp")
        if "modelName" not in payload and "model" in payload:
            payload["modelName"] = payload.get("model")
        if "instanceId" not in payload and "contextId" in payload:
            payload["instanceId"] = payload.get("contextId")
        original_id = str(payload.get("id") or "")
        run_id = str(payload.get("trialId") or payload.get("id") or "")
        payload["trialId"] = run_id
        payload["id"] = run_id
        if "metadata" not in payload:
            payload["metadata"] = {
                "canonicalId": original_id or run_id,
                "taskId": payload.get("taskId", ""),
                "instanceId": payload.get("instanceId", payload.get("contextId", "")),
                "provider": payload.get("provider", ""),
                "modelId": payload.get("modelId"),
                "modelName": payload.get("modelName"),
                "strategy": payload.get("strategy", ""),
                "format": payload.get("format", ""),
                "repeatIndex": payload.get("repeatIndex", 1),
                "validationConfig": payload.get("validationConfig", {}),
                "parameters": payload.get("parameters", {}),
            }
        validated_metadata = TrialMetadata.model_validate(payload["metadata"])
        payload["metadata"] = validated_metadata
        payload.setdefault("taskTags", validated_metadata.taskTags)
        payload.setdefault("validationType", validated_metadata.validationType)
        payload.setdefault("validationConfig", validated_metadata.validationConfig)
        payload.setdefault("parameters", validated_metadata.parameters)
        payload.setdefault("modelId", validated_metadata.modelId or payload.get("modelName"))
        payload = _coerce_dataset_provenance(payload)
        return super().model_validate(payload)

    def to_persisted_artifact(self) -> dict[str, Any]:
        return {
            "trialId": self.trialId,
            "experimentId": self.experimentId,
            "taskId": self.taskId,
            "taskStatement": self.taskStatement,
            "taskTemplate": self.taskTemplate,
            "dataset": self.dataset.model_dump(mode="json"),
            "instanceId": self.instanceId,
            "model": self.modelName,
            "modelId": self.modelId,
            "provider": self.provider,
            "strategy": self.strategy,
            "format": self.format,
            "params": self.params,
            "repeatIndex": self.repeatIndex,
            "outputRoot": self.outputRoot,
            "evaluationEnabled": self.evaluationEnabled,
            "trace": self.trace.model_dump(mode="json"),
            "artifacts": self.artifacts.model_dump(mode="json"),
            "taskTags": list(self.taskTags),
            "validationType": self.validationType,
            "validationConfig": dict(self.validationConfig),
            "contextBlocks": list(self.contextBlocks),
            "parameters": dict(self.parameters),
            "metadata": {
                "canonicalId": self.metadata.canonicalId,
                "taskId": self.metadata.taskId,
                "instanceId": self.metadata.instanceId,
                "provider": self.metadata.provider,
                "modelId": self.metadata.modelId,
                "modelName": self.metadata.modelName,
                "strategy": self.metadata.strategy,
                "format": self.metadata.format,
                "repeatIndex": self.metadata.repeatIndex,
                "taskTags": list(self.metadata.taskTags),
                "validationType": self.metadata.validationType,
                "validationConfig": dict(self.metadata.validationConfig),
                "parameters": dict(self.metadata.parameters),
            },
        }


RunSpec = TrialSpec


class RunTiming(BaseModel):
    startedAt: str
    finishedAt: str
    durationMs: int


class TrialTrace(BaseModel):
    aiTrace: dict[str, Any] = Field(default_factory=dict)
    toolCalls: list[dict[str, Any]] = Field(default_factory=list)
    nativeMcp: dict[str, Any] = Field(default_factory=dict)
    serverMcp: list[dict[str, Any]] = Field(default_factory=list)
    rawResponse: Any | None = None
    error: str | None = None


RunTrace = TrialTrace


class EvaluationResult(BaseModel):
    status: str = "not_evaluated"
    passed: bool | None = None
    expected: Any | None = None
    reason: str | None = None
    evaluator: str | None = None


class TrialResult(BaseModel):
    trialId: str
    experimentId: str
    dataset: DatasetProvenance
    taskId: str
    taskStatement: str = ""
    taskTemplate: str | None = None
    taskTags: list[str] = Field(default_factory=list)
    validationType: str | None = None
    validationConfig: dict[str, Any] = Field(default_factory=dict)
    contextBlocks: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    instanceId: str
    provider: str
    modelId: str | None = None
    modelName: str | None = None
    strategy: str
    format: str
    repeatIndex: int
    outputRoot: str | None = None
    response: str
    status: str
    errorMessage: str | None = None
    timing: RunTiming
    usage: dict[str, Any] = Field(default_factory=dict)
    metricsSummary: dict[str, Any] = Field(default_factory=dict)
    trace: TrialTrace = Field(default_factory=TrialTrace)
    traceRef: str | None = None
    evaluation: EvaluationResult = Field(default_factory=EvaluationResult)
    metadata: TrialMetadata

    @classmethod
    def model_validate(cls, data: Any) -> "TrialResult":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("TrialResult requires an object input.")
        payload = dict(data)
        if "runId" in payload:
            raise ValueError("Public TrialResult input must use 'trialId', not 'runId'.")
        if "questionId" in payload:
            raise ValueError("Public TrialResult input must use 'taskId', not 'questionId'.")
        if "answer" in payload:
            raise ValueError("Public TrialResult input must use 'response', not 'answer'.")
        if "question" in payload:
            raise ValueError("Public TrialResult input must use 'taskStatement', not 'question'.")
        strategy = payload.get("strategy")
        if isinstance(strategy, str) and strategy == "mcp":
            raise ValueError("unknown strategy: mcp")
        if "modelName" not in payload and "model" in payload:
            payload["modelName"] = payload.get("model")
        if "instanceId" not in payload and "contextId" in payload:
            payload["instanceId"] = payload.get("contextId")
        original_id = str(payload.get("id") or "")
        run_id = str(payload.get("trialId") or payload.get("id") or "")
        payload["trialId"] = run_id
        if "metadata" not in payload:
            payload["metadata"] = {
                "canonicalId": original_id or run_id,
                "taskId": payload.get("taskId", ""),
                "instanceId": payload.get("instanceId", payload.get("contextId", "")),
                "provider": payload.get("provider", ""),
                "modelId": payload.get("modelId"),
                "modelName": payload.get("modelName"),
                "strategy": payload.get("strategy", ""),
                "format": payload.get("format", ""),
                "repeatIndex": payload.get("repeatIndex", 1),
                "validationConfig": payload.get("validationConfig", {}),
                "parameters": payload.get("parameters", {}),
            }
        validated_metadata = TrialMetadata.model_validate(payload["metadata"])
        payload["metadata"] = validated_metadata
        payload.setdefault("taskTags", validated_metadata.taskTags)
        payload.setdefault("validationType", validated_metadata.validationType)
        payload.setdefault("validationConfig", validated_metadata.validationConfig)
        payload.setdefault("parameters", validated_metadata.parameters)
        payload.setdefault("modelId", validated_metadata.modelId or payload.get("modelName"))
        payload = _coerce_dataset_provenance(payload)
        return super().model_validate(payload)

    def to_persisted_artifact(self, *, trace_ref: str | None = None) -> dict[str, Any]:
        return {
            "trialId": self.trialId,
            "experimentId": self.experimentId,
            "taskId": self.taskId,
            "taskStatement": self.taskStatement,
            "taskTemplate": self.taskTemplate,
            "dataset": self.dataset.model_dump(mode="json"),
            "instanceId": self.instanceId,
            "provider": self.provider,
            "modelId": self.modelId,
            "model": self.modelName,
            "strategy": self.strategy,
            "format": self.format,
            "repeatIndex": self.repeatIndex,
            "outputRoot": self.outputRoot,
            "status": self.status,
            "response": self.response,
            "errorMessage": self.errorMessage,
            "timing": self.timing.model_dump(mode="json"),
            "usage": self.usage,
            "metricsSummary": self.metricsSummary,
            "traceRef": trace_ref,
            "taskTags": list(self.taskTags),
            "validationType": self.validationType,
            "validationConfig": dict(self.validationConfig),
            "contextBlocks": list(self.contextBlocks),
            "parameters": dict(self.parameters),
            "metadata": {
                "canonicalId": self.metadata.canonicalId,
                "taskId": self.metadata.taskId,
                "instanceId": self.metadata.instanceId,
                "provider": self.metadata.provider,
                "modelId": self.metadata.modelId,
                "modelName": self.metadata.modelName,
                "strategy": self.metadata.strategy,
                "format": self.metadata.format,
                "repeatIndex": self.metadata.repeatIndex,
                "taskTags": list(self.metadata.taskTags),
                "validationType": self.metadata.validationType,
                "validationConfig": dict(self.metadata.validationConfig),
                "parameters": dict(self.metadata.parameters),
            },
        }


RunResult = TrialResult


class EvaluationTrace(BaseModel):
    aiTrace: dict[str, Any] = Field(default_factory=dict)
    rawResponse: Any | None = None
    error: str | None = None


class EvaluationJudgeInfo(BaseModel):
    used: bool = False
    role: str | None = None
    provider: str | None = None
    model: str | None = None
    inputTokens: int | None = None
    outputTokens: int | None = None
    durationMs: int | None = None
    fallbackUsed: bool = False


class EvaluationItemResult(BaseModel):
    experimentId: str
    trialId: str
    dataset: DatasetProvenance
    taskId: str
    instanceId: str | None = None
    taskStatement: str
    evaluationMode: str
    status: str = "evaluated"
    evaluationMethod: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    executionModel: str | None = None
    executionStrategy: str | None = None
    executionFormat: str | None = None
    executionInputTokens: int | None = None
    executionOutputTokens: int | None = None
    executionDurationMs: int | None = None
    executionToolCalls: int | None = None
    executionFunctionCalls: int | None = None
    executionLlmCalls: int | None = None
    taskTags: list[str] = Field(default_factory=list)
    evaluationJudgeUsed: bool = False
    evaluationJudgeRole: str | None = None
    evaluationJudgeProvider: str | None = None
    evaluationJudgeModel: str | None = None
    evaluationInputTokens: int | None = None
    evaluationOutputTokens: int | None = None
    evaluationDurationMs: int | None = None
    evaluationTrace: EvaluationTrace = Field(default_factory=EvaluationTrace)
    contextBlocks: list[str] | None = None

    @classmethod
    def model_validate(cls, data: Any) -> "EvaluationItemResult":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("EvaluationItemResult requires an object input.")
        return super().model_validate(_coerce_dataset_provenance(dict(data)))

    def to_persisted_artifact(self) -> dict[str, Any]:
        details = self.details if isinstance(self.details, dict) else {}
        outcome = details.get("outcome") if isinstance(details.get("outcome"), dict) else {}
        judges: list[dict[str, Any]] = details.get("judges") or []
        judge_success_count = sum(1 for j in judges if isinstance(j, dict) and not j.get("error"))
        judge_error_count = sum(1 for j in judges if isinstance(j, dict) and j.get("error"))
        if self.status == "skipped":
            eval_status = "skipped"
        elif self.evaluationMethod == "repoqa-scorer":
            eval_status = "evaluated"
        elif judge_success_count == 0:
            eval_status = "error"
        elif judge_error_count > 0:
            eval_status = "partial"
        else:
            eval_status = "evaluated"
        eval_total = (
            (self.evaluationInputTokens or 0) + (self.evaluationOutputTokens or 0)
            if self.evaluationInputTokens is not None or self.evaluationOutputTokens is not None
            else None
        )
        payload = {
            "trialId": self.trialId,
            "experimentId": self.experimentId,
            "dataset": self.dataset.model_dump(mode="json"),
            "instanceId": self.instanceId,
            "taskId": self.taskId,
            "strategy": self.executionStrategy,
            "status": eval_status,
            "evaluationMethod": self.evaluationMethod,
            "judgeCount": judge_success_count,
            "judgeErrorCount": judge_error_count,
            "outcome": outcome or None,
            "evaluationInputTokens": self.evaluationInputTokens,
            "evaluationOutputTokens": self.evaluationOutputTokens,
            "evaluationTotalTokens": eval_total,
            "evaluationDurationMs": self.evaluationDurationMs,
            "contextBlocks": self.contextBlocks if self.contextBlocks else None,
        }
        if self.evaluationMethod == "repoqa-scorer":
            payload["details"] = details
        return payload

    def to_judge_votes(self, *, trace_ref: str | None = None) -> list[dict[str, Any]]:
        details = self.details if isinstance(self.details, dict) else {}
        judges: list[Any] = details.get("judges") or []
        votes: list[dict[str, Any]] = []
        for judge in judges:
            if not isinstance(judge, dict):
                continue
            correctness = judge.get("correctness") or {}
            completeness = judge.get("completeness") or {}
            total_tokens = None
            inp = judge.get("inputTokens")
            out = judge.get("outputTokens")
            if inp is not None or out is not None:
                total_tokens = (inp or 0) + (out or 0)
            votes.append({
                "trialId": self.trialId,
                "experimentId": self.experimentId,
                "dataset": self.dataset.model_dump(mode="json"),
                "instanceId": self.instanceId,
                "taskId": self.taskId,
                "strategy": self.executionStrategy,
                "judgeId": judge.get("judgeId"),
                "provider": judge.get("provider"),
                "model": judge.get("model"),
                "status": judge.get("status") if isinstance(judge.get("status"), str) else ("error" if judge.get("error") else "evaluated"),
                "criterias": {
                    "correctness": {
                        "rating": correctness.get("rating") if isinstance(correctness, dict) else None,
                        "justification": correctness.get("justification") if isinstance(correctness, dict) else None,
                    },
                    "completeness": {
                        "rating": completeness.get("rating") if isinstance(completeness, dict) else None,
                        "justification": completeness.get("justification") if isinstance(completeness, dict) else None,
                    },
                },
                "inputTokens": inp,
                "outputTokens": out,
                "totalTokens": total_tokens,
                "durationMs": judge.get("durationMs"),
                "error": judge.get("error"),
                "traceRef": trace_ref,
            })
        return votes


class EvaluationRunSummary(BaseModel):
    itemCount: int = 0


class EvaluationTrialResult(BaseModel):
    experimentId: str
    trialId: str
    dataset: DatasetProvenance
    taskId: str
    items: list[EvaluationItemResult] = Field(default_factory=list)
    summary: EvaluationRunSummary = Field(default_factory=EvaluationRunSummary)
    metadata: TrialMetadata

    @classmethod
    def model_validate(cls, data: Any) -> "EvaluationTrialResult":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("EvaluationTrialResult requires an object input.")
        payload = dict(data)
        if "runId" in payload:
            raise ValueError("Public EvaluationTrialResult input must use 'trialId', not 'runId'.")
        if "questionId" in payload:
            raise ValueError("Public EvaluationTrialResult input must use 'taskId', not 'questionId'.")
        if "metadata" not in payload:
            payload["metadata"] = {
                "canonicalId": str(payload.get("trialId", "")),
                "taskId": payload.get("taskId", ""),
                "instanceId": "",
                "provider": "",
                "modelId": None,
                "modelName": None,
                "strategy": "",
                "format": "",
                "repeatIndex": 1,
            }
        else:
            payload["metadata"] = TrialMetadata.model_validate(payload["metadata"])
        payload = _coerce_dataset_provenance(payload)
        return super().model_validate(payload)


EvaluationRunResult = EvaluationTrialResult


class EvaluationBatchSummary(BaseModel):
    experimentId: str
    runCount: int = 0
    itemCount: int = 0
    tasks: list[dict[str, Any]] = Field(default_factory=list)
