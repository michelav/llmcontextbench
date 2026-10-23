"""Resolve v1 definition files before adapting them to the existing trial planner.

The adapter is deliberately at the definition boundary: provider/runtime code does
not need to understand inheritance or the historical factorial input format.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import json

DEFINITION_VERSION = 3


def _merge(parent: dict, child: dict) -> dict:
    result = deepcopy(parent)
    for key, value in child.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            base = result.get(key)
            result[key] = _merge(base if isinstance(base, dict) else {}, value)
        else:
            result[key] = deepcopy(value)
    return result


def resolve_definition(path: str | Path, *, _parents: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Resolve one parent, preserving the origin of each declared input path."""
    source = Path(path).resolve()
    if source in _parents:
        raise ValueError(f"Definition inheritance cycle: {source}")
    if len(_parents) >= 32:
        raise ValueError("Definition inheritance exceeds 32 files")
    with source.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"Definition must be an object: {source}")
    parent = data.pop("extends", None)
    if parent is not None and (not isinstance(parent, str) or not parent.strip()):
        raise ValueError("extends must be a nonempty path string")
    # Only input paths are rebased. Outputs remain relative to the leaf definition.
    dataset = data.get("dataset")
    if (data.get("schemaVersion") is not None or parent) and isinstance(dataset, dict) and isinstance(dataset.get("root"), str):
        root = Path(dataset["root"]).expanduser()
        dataset["root"] = str((source.parent / root).resolve())
    if (data.get("schemaVersion") is not None or parent) and isinstance(dataset, str):
        data["dataset"] = str((source.parent / Path(dataset).expanduser()).resolve())
    if parent:
        base = resolve_definition(source.parent / parent, _parents=(*_parents, source))
        return _merge(base, data)
    return data


def planner_payload(definition: dict[str, Any]) -> dict[str, Any]:
    """Validate the v1 public contract and translate to the shared planner model.

Unversioned definitions remain for the old study stack during its staged removal.
No persisted-artifact compatibility reading is introduced here.
"""
    version = definition.get("schemaVersion")
    if version is None:
        return deepcopy(definition)
    if type(version) is not int or version != DEFINITION_VERSION:
        raise ValueError(f"Unsupported experiment schemaVersion; expected {DEFINITION_VERSION}")
    from jsonschema import Draft202012Validator
    Draft202012Validator(definition_schema()).validate(definition)
    result = deepcopy(definition)
    if result.pop("kind", "benchmark") != "benchmark":
        raise ValueError("Adaptive definitions require the adaptive planner")
    result.pop("schemaVersion")
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
    result["descriptiveFactors"] = result.pop("factorsMetadata", {})
    return result


def definition_schema() -> dict[str, Any]:
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
            "factorsMetadata": {"type": "object"},
            "execution": {"type": "object", "additionalProperties": False, "properties": {
                "repeats": {"type": "integer", "minimum": 1}, "output": {"type": "string"},
                "jsonl": {"type": "string"}, "options": {"type": "object"}}},
            "evaluation": {"type": "object"}, "trace": {"type": "object"}, "artifacts": {"type": "object"},
        },
    }
