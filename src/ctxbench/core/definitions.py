"""Shared definition inheritance resolver."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import json


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


def resolve_definition_data(definition: dict[str, Any], *, base_dir: str | Path) -> dict[str, Any]:
    """Resolve a mapping definition with the same relative-path rules as a file leaf."""
    source_dir = Path(base_dir).resolve()
    data = deepcopy(definition)
    parent = data.pop("extends", None)
    if parent is not None and (not isinstance(parent, str) or not parent.strip()):
        raise ValueError("extends must be a nonempty path string")
    dataset = data.get("dataset")
    if (data.get("schemaVersion") is not None or parent) and isinstance(dataset, dict) and isinstance(dataset.get("root"), str):
        data["dataset"]["root"] = str((source_dir / Path(dataset["root"]).expanduser()).resolve())
    elif (data.get("schemaVersion") is not None or parent) and isinstance(dataset, str):
        data["dataset"] = str((source_dir / Path(dataset).expanduser()).resolve())
    if parent:
        return _merge(resolve_definition(source_dir / parent), data)
    return data


__all__ = ["resolve_definition", "resolve_definition_data"]
