"""Typed adaptive experiment definition and v4 validation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ctxbench.core.definitions import resolve_definition, resolve_definition_data


ADAPTIVE_DEFINITION_VERSION = 4


@dataclass(frozen=True, slots=True)
class WorkloadRequest:
    task_id: str
    instance_id: str
    request_id: str | None = None
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AdaptiveExperiment:
    """Parsed adaptive definition; this is the same model used by file and object planning."""

    id: str
    dataset: str | Mapping[str, Any]
    models: Mapping[str, Mapping[str, Any]]
    surfaces: Mapping[str, Mapping[str, Any]]
    configurations: Mapping[str, Mapping[str, Any]]
    candidates: Mapping[str, Mapping[str, Any]]
    workload: tuple[WorkloadRequest, ...]
    policy: Mapping[str, Any]
    window: Mapping[str, Any]
    seed: int = 0
    output: str = "outputs"
    labels: Mapping[str, str] = field(default_factory=dict)
    task_params: Mapping[str, Any] = field(default_factory=dict)
    execution_options: Mapping[str, Any] = field(default_factory=dict)
    acceptance: Mapping[str, Any] = field(default_factory=dict)
    signals: tuple[Mapping[str, Any], ...] = ()
    goals: tuple[Mapping[str, Any], ...] = ()
    disturbances: tuple[Mapping[str, Any], ...] = ()
    evaluation: Mapping[str, Any] = field(default_factory=dict)
    trace: Mapping[str, Any] = field(default_factory=dict)
    allow_mixed_models: bool = False
    base_dir: Path = Path.cwd()
    resolved_definition: Mapping[str, Any] = field(default_factory=dict)


def adaptive_definition_schema() -> dict[str, Any]:
    """Strict Python schema for the initial explicit-workload v4 contract."""
    label_map = {"type": "object", "additionalProperties": {"type": "string"}}
    assessor = {"type": "object", "additionalProperties": False,
                "required": ["id", "assessor"],
                "properties": {"id": {"type": "string", "minLength": 1},
                               "assessor": {"type": "string", "minLength": 1}}}
    goal = {"type": "object", "additionalProperties": False,
            "required": ["id", "signal", "statistic"],
            "properties": {"id": {"type": "string", "minLength": 1},
                           "signal": {"type": "string", "minLength": 1},
                           "statistic": {"type": "string", "minLength": 1},
                           "upper": {"type": "number"}, "lower": {"type": "number"},
                           "scope": {"type": "string"}, "window": {"type": "object"}},
            "oneOf": [{"required": ["upper"], "not": {"required": ["lower"]}},
                      {"required": ["lower"], "not": {"required": ["upper"]}}]}
    disturbance = {"type": "object", "additionalProperties": False,
                   "required": ["name", "version", "component", "kind"],
                   "properties": {"name": {"type": "string", "minLength": 1},
                                  "version": {"type": "string", "minLength": 1},
                                  "component": {"enum": ["local_function", "local_mcp", "remote_mcp", "model"]},
                                  "kind": {"enum": ["delay", "failure"]},
                                  "delayMs": {"type": "number", "minimum": 0},
                                  "failureRate": {"type": "number", "minimum": 0, "maximum": 1},
                                  "firstSequence": {"type": "integer", "minimum": 1},
                                  "lastSequence": {"type": "integer", "minimum": 1},
                                  "seed": {"type": "integer"},
                                  "candidates": {"type": "array", "items": {"type": "string", "minLength": 1}}}}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": ["workflowKind", "schemaVersion", "id", "dataset", "models", "surfaces",
                     "configurations", "candidates", "workload", "policy", "window"],
        "properties": {
            "workflowKind": {"const": "adaptive"}, "schemaVersion": {"const": ADAPTIVE_DEFINITION_VERSION},
            "id": {"type": "string", "minLength": 1}, "output": {"type": "string", "minLength": 1},
            "seed": {"type": "integer"}, "labels": label_map,
            "allowMixedModels": {"type": "boolean"},
            "dataset": {"oneOf": [
                {"type": "string", "minLength": 1},
                {"type": "object", "additionalProperties": False,
                 "properties": {"id": {"type": "string"}, "version": {"type": "string"},
                                "root": {"type": "string"}, "origin": {"type": "string"}},
                 "anyOf": [{"required": ["root"]}, {"required": ["id", "version"]}]},
            ]},
            "models": {"type": "object", "minProperties": 1, "additionalProperties": {
                "type": "object", "additionalProperties": False, "required": ["provider", "name"],
                "properties": {"provider": {"type": "string", "minLength": 1},
                               "name": {"type": "string", "minLength": 1},
                               "modelParams": {"type": "object"}}}},
            "surfaces": {"type": "object", "minProperties": 1, "additionalProperties": {
                "oneOf": [
                    {"type": "object", "additionalProperties": False,
                     "properties": {"type": {"const": "full_context"}}},
                    {"type": "object", "additionalProperties": False,
                     "required": ["type", "operations"],
                     "properties": {"type": {"const": "operations"},
                                    "operations": {"type": "array", "minItems": 1,
                                                   "items": {"type": "string", "minLength": 1}}}},
                ]}},
            "configurations": {"type": "object", "minProperties": 1, "additionalProperties": {
                "type": "object", "additionalProperties": False,
                "required": ["strategy", "representation", "surface"],
                "properties": {"strategy": {"enum": ["inline", "local_function", "local_mcp", "remote_mcp"]},
                               "representation": {"type": "string", "minLength": 1},
                               "surface": {"type": "string", "minLength": 1}}}},
            "candidates": {"type": "object", "minProperties": 1, "additionalProperties": {
                "type": "object", "additionalProperties": False, "required": ["model", "configuration"],
                "properties": {"model": {"type": "string", "minLength": 1},
                               "configuration": {"type": "string", "minLength": 1},
                               "labels": label_map}}},
            "taskParams": {"type": "object"},
            "execution": {"type": "object", "additionalProperties": False,
                          "properties": {"options": {"type": "object"}}},
            "workload": {"type": "object", "additionalProperties": False, "required": ["requests"],
                         "properties": {"requests": {"type": "array", "minItems": 1, "items": {
                             "type": "object", "additionalProperties": False,
                             "required": ["taskId", "instanceId"],
                             "properties": {"requestId": {"type": "string", "minLength": 1},
                                            "taskId": {"type": "string", "minLength": 1},
                                            "instanceId": {"type": "string", "minLength": 1},
                                            "labels": label_map}}}}},
            "policy": {"type": "object", "additionalProperties": False, "required": ["ref"],
                       "properties": {"ref": {"type": "string", "minLength": 1},
                                      "params": {"type": "object"},
                                      "sources": {"type": "array", "items": {"type": "string", "minLength": 1}}}},
            "window": {"type": "object", "additionalProperties": False, "required": ["requests"],
                       "properties": {"requests": {"type": "integer", "minimum": 1},
                                      "mode": {"enum": ["sliding", "fixed"]}}},
            "signals": {"type": "array", "items": assessor},
            "acceptance": {"type": "object", "additionalProperties": False,
                           "properties": {"minimumResponseLength": {"type": "integer", "minimum": 0}}},
            "goals": {"type": "array", "items": goal},
            "disturbances": {"type": "array", "items": disturbance},
            "evaluation": {"type": "object", "additionalProperties": False,
                            "properties": {"enabled": {"type": "boolean"},
                                           "judges": {"type": "array"}}},
            "trace": {"type": "object", "additionalProperties": False,
                      "properties": {"enabled": {"type": "boolean"},
                                     "writeFiles": {"type": "boolean"}}},
        },
    }


def load_adaptive_experiment(source: str | Path | Mapping[str, Any], *, base_dir: str | Path | None = None) -> AdaptiveExperiment:
    if isinstance(source, Mapping):
        actual_base = Path(base_dir or Path.cwd()).resolve()
        resolved = resolve_definition_data(dict(source), base_dir=actual_base)
    else:
        path = Path(source).expanduser().resolve()
        actual_base = path.parent
        resolved = resolve_definition(path)
    from jsonschema import Draft202012Validator
    errors = sorted(Draft202012Validator(adaptive_definition_schema()).iter_errors(resolved),
                    key=lambda err: list(err.absolute_path))
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.absolute_path) or "$"
        raise ValueError(f"Invalid adaptive definition at {location}: {first.message}")
    requests = tuple(WorkloadRequest(
        task_id=row["taskId"], instance_id=row["instanceId"],
        request_id=row.get("requestId"), labels=dict(row.get("labels") or {}),
    ) for row in resolved["workload"]["requests"])
    return AdaptiveExperiment(
        id=resolved["id"], dataset=resolved["dataset"], models=deepcopy(resolved["models"]),
        surfaces=deepcopy(resolved["surfaces"]), configurations=deepcopy(resolved["configurations"]),
        candidates=deepcopy(resolved["candidates"]), workload=requests,
        policy=deepcopy(resolved["policy"]), window=deepcopy(resolved["window"]),
        seed=resolved.get("seed", 0), output=resolved.get("output", "outputs"),
        labels=deepcopy(resolved.get("labels") or {}), task_params=deepcopy(resolved.get("taskParams") or {}),
        execution_options=deepcopy((resolved.get("execution") or {}).get("options") or {}),
        acceptance=deepcopy(resolved.get("acceptance") or {}),
        signals=tuple(deepcopy(resolved.get("signals") or [])), goals=tuple(deepcopy(resolved.get("goals") or [])),
        disturbances=tuple(deepcopy(resolved.get("disturbances") or [])),
        evaluation=deepcopy(resolved.get("evaluation") or {}), trace=deepcopy(resolved.get("trace") or {}),
        allow_mixed_models=resolved.get("allowMixedModels", False), base_dir=actual_base,
        resolved_definition=deepcopy(resolved),
    )


__all__ = ["ADAPTIVE_DEFINITION_VERSION", "AdaptiveExperiment", "WorkloadRequest",
           "adaptive_definition_schema", "load_adaptive_experiment"]
