"""Benchmark-specific definition validation and planner conversion.

Definition inheritance is shared by workflows and lives in ``ctxbench.core.definitions``.
This module re-exports that resolver for existing callers.
"""
from __future__ import annotations

from copy import deepcopy

from ctxbench.core.definitions import resolve_definition

DEFINITION_VERSION = 3


def planner_payload(definition: dict) -> dict:
    """Validate the current benchmark contract and translate it to planner models."""
    version = definition.get("schemaVersion")
    if version is None:
        raise ValueError("Unversioned definitions are unsupported; create a fresh benchmark definition.")
    if type(version) is not int or version != DEFINITION_VERSION:
        raise ValueError(f"Unsupported experiment schemaVersion; expected {DEFINITION_VERSION}")
    from jsonschema import Draft202012Validator
    Draft202012Validator(definition_schema()).validate(definition)
    result = deepcopy(definition)
    kind = result.pop("kind", "benchmark")
    if kind != "benchmark":
        raise ValueError("Benchmark definitions require kind='benchmark'; use workflowKind='adaptive' for adaptive plans.")
    result.pop("schemaVersion")
    result["resolvedDefinition"] = deepcopy(definition)
    models = result["models"]
    reserved = {"max_steps", "mcp_server", "timeout", "retry"}
    for params in [result.get("modelParams", {}), *(m.get("modelParams", {}) for m in models.values())]:
        if reserved & params.keys():
            raise ValueError("Execution settings belong in execution.options, not modelParams")
    for key, entry in models.items():
        if not key or not entry["provider"].strip() or not entry["name"].strip():
            raise ValueError("Model identifiers, providers and names must be nonempty")
        entry["params"] = entry.pop("modelParams", {})
    candidates = result.pop("candidates")
    seen: set[tuple[str, str]] = set()
    for model, configuration in candidates:
        pair = (model, configuration)
        if pair in seen:
            raise ValueError(f"Duplicate candidate: {pair}")
        if model not in models or configuration not in result["configurations"]:
            raise ValueError(f"Unknown candidate reference: {pair}")
        seen.add(pair)
    result["selectedCandidates"] = candidates
    result["factors"] = {
        "model": list(dict.fromkeys(pair[0] for pair in candidates)),
        "configuration": list(dict.fromkeys(pair[1] for pair in candidates)),
    }
    common = result.pop("modelParams", {})
    result["params"] = {"common": common}
    # Generation and orchestration controls have distinct public ownership.
    execution = result.get("execution", {})
    result["executionOptions"] = execution.pop("options", {})
    return result


def definition_schema() -> dict:
    """Schema is defined in Python so installed wheels validate without repo paths."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": ["schemaVersion", "id", "dataset", "models", "configurations", "surfaces", "candidates"],
        "properties": {
            "schemaVersion": {"const": DEFINITION_VERSION},
            "kind": {"const": "benchmark"},
            "id": {"type": "string", "minLength": 1},
            "name": {"type": "string"}, "output": {"type": "string"},
            "dataset": {"oneOf": [{"type": "string"}, {"type": "object"}]},
            "scope": {"type": "object"},
            "models": {"type": "object", "minProperties": 1, "additionalProperties": {
                "type": "object", "additionalProperties": False, "required": ["provider", "name"],
                "properties": {"provider": {"type": "string", "minLength": 1},
                               "name": {"type": "string", "minLength": 1}, "modelParams": {"type": "object"}}}},
            "configurations": {"type": "object", "minProperties": 1},
            "surfaces": {"type": "object", "minProperties": 1},
            "candidates": {"type": "array", "minItems": 1, "items": {
                "type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "string", "minLength": 1}}},
            "taskParams": {"type": "object"}, "modelParams": {"type": "object"},
            "execution": {"type": "object", "additionalProperties": False, "properties": {
                "repeats": {"type": "integer", "minimum": 1}, "options": {"type": "object"}}},
            "evaluation": {"type": "object"}, "trace": {"type": "object"}, "artifacts": {"type": "object"},
        },
    }


__all__ = ["DEFINITION_VERSION", "definition_schema", "planner_payload", "resolve_definition"]
