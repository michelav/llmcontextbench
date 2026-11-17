"""Deterministic construction of ordered request workloads."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Mapping, Sequence

from ctxbench.dataset.capabilities import RequestFeatureSchema


@dataclass(frozen=True, slots=True)
class DatasetHandle:
    """Read-only dataset metadata used while constructing a workload."""

    package: Any = field(repr=False, compare=False)
    feature_schema: RequestFeatureSchema | None
    task_ids: tuple[str, ...]
    instance_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Segment:
    size: int
    where: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.size) is not int or self.size < 1:
            raise ValueError("segments.size must be a positive integer")
        if not isinstance(self.where, Mapping):
            raise ValueError("segments.where must be an object")

    def to_definition(self) -> dict[str, Any]:
        return {"size": self.size, **({"where": dict(self.where)} if self.where else {})}

    @classmethod
    def from_definition(cls, definition: Mapping[str, Any]) -> "Segment":
        return cls(size=definition["size"], where=dict(definition.get("where") or {}))


@dataclass(frozen=True, slots=True)
class Workload:
    """Input workload section. Generated requests are expanded during planning."""

    definition: Mapping[str, Any]

    def to_definition(self) -> dict[str, Any]:
        return _plain(self.definition)

    @classmethod
    def explicit(cls, requests: Sequence[Any]) -> "Workload":
        rows = []
        for request in requests:
            if hasattr(request, "to_definition"):
                row = request.to_definition()
            elif isinstance(request, Mapping):
                row = dict(request)
            else:
                row = {"taskId": request.task_id, "instanceId": request.instance_id}
                if getattr(request, "request_id", None) is not None:
                    row["requestId"] = request.request_id
                if getattr(request, "labels", None):
                    row["labels"] = dict(request.labels)
            rows.append(row)
        return cls({"requests": rows})

    @classmethod
    def generate(cls, dataset: DatasetHandle, segments: Sequence[Segment | Mapping[str, Any]], *,
                 seed: int, tasks: Sequence[str] = (), instances: Sequence[str] = (),
                 sampling: str = "with_replacement", label_features: Sequence[str] = ()) -> "Workload":
        if not isinstance(dataset, DatasetHandle):
            raise TypeError("Workload.generate requires a DatasetHandle returned by load_dataset")
        if type(seed) is not int:
            raise ValueError("generator.seed must be an integer")
        normalized_segments = [segment if isinstance(segment, Segment) else Segment.from_definition(segment)
                              for segment in segments]
        if not normalized_segments:
            raise ValueError("generator.segments must contain at least one segment")
        if sampling not in {"with_replacement", "without_replacement"}:
            raise ValueError("generator.sampling must be 'with_replacement' or 'without_replacement'")
        task_ids = _scope_ids("tasks", tasks, dataset.task_ids)
        instance_ids = _scope_ids("instances", instances, dataset.instance_ids)
        feature_ids = {feature.feature_id for feature in dataset.feature_schema.features} \
            if dataset.feature_schema else set()
        unknown_labels = set(label_features) - feature_ids
        if unknown_labels:
            raise ValueError(f"Unknown request feature(s) in generator.labelFeatures: {', '.join(sorted(unknown_labels))}")
        generator = {
            "seed": seed, "tasks": list(tasks), "instances": list(instances),
            "sampling": sampling, "segments": [item.to_definition() for item in normalized_segments],
            "labelFeatures": list(label_features),
        }
        # Validate filters at construction as well as expansion, before a plan is created.
        for segment in normalized_segments:
            _validate_filter(segment.where, dataset.feature_schema)
        workload = cls({"generator": generator})
        generate_requests(dataset, generator)
        return workload


def generate_requests(dataset: DatasetHandle, generator: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Expand a validated generator using stable SHA-256 ordering, independent of process state."""
    task_ids = _scope_ids("tasks", generator.get("tasks", ()), dataset.task_ids)
    instance_ids = _scope_ids("instances", generator.get("instances", ()), dataset.instance_ids)
    feature_schema = dataset.feature_schema
    declared = {feature.feature_id for feature in feature_schema.features} if feature_schema else set()
    label_features = tuple(generator.get("labelFeatures", ()))
    unknown_labels = set(label_features) - declared
    if unknown_labels:
        raise ValueError(f"Unknown request feature(s) in generator.labelFeatures: {', '.join(sorted(unknown_labels))}")

    pool: list[tuple[str, str]] = []
    for task_id in task_ids:
        for instance_id in instance_ids:
            supported_tasks = getattr(dataset.package, "list_task_ids_for_instance", None)
            if callable(supported_tasks) and task_id not in supported_tasks(instance_id):
                continue
            pool.append((task_id, instance_id))
    pool.sort()
    if not pool:
        raise ValueError("Workload generator produced an empty task/instance pool")

    seed = generator["seed"]
    sampling = generator.get("sampling", "with_replacement")
    if sampling not in {"with_replacement", "without_replacement"}:
        raise ValueError("generator.sampling must be 'with_replacement' or 'without_replacement'")
    output: list[dict[str, Any]] = []
    for segment_index, raw_segment in enumerate(generator["segments"]):
        segment = raw_segment if isinstance(raw_segment, Segment) else Segment.from_definition(raw_segment)
        _validate_filter(segment.where, feature_schema)
        filtered = [pair for pair in pool if _matches_where(
            segment.where, dataset.package.request_features(pair[1], pair[0]), feature_schema
        )]
        if not filtered:
            raise ValueError(f"generator.segments[{segment_index}] filter matches no task/instance pairs")
        if sampling == "without_replacement" and segment.size > len(filtered):
            raise ValueError(
                f"generator.segments[{segment_index}].size ({segment.size}) exceeds its filtered pool ({len(filtered)})"
            )
        ranked = sorted(filtered, key=lambda pair: (_rank(seed, segment_index, pair), pair))
        if sampling == "without_replacement":
            selected = ranked[:segment.size]
        else:
            selected = [ranked[index % len(ranked)] for index in
                        (_draw_index(seed, segment_index, draw, len(ranked)) for draw in range(segment.size))]
        for task_id, instance_id in selected:
            features = dataset.package.request_features(instance_id, task_id)
            labels = {key: _label_value(features.get(key)) for key in label_features}
            output.append({"requestId": f"r-{len(output) + 1:04d}", "taskId": task_id,
                           "instanceId": instance_id, **({"labels": labels} if labels else {})})
    pool_digest = sha256(_canonical_json(pool).encode("utf-8")).hexdigest()
    return output, pool_digest


def _scope_ids(name: str, selected: Sequence[str], available: Sequence[str]) -> tuple[str, ...]:
    available_set = set(available)
    if not selected:
        return tuple(sorted(available_set))
    unknown = set(selected) - available_set
    if unknown:
        raise ValueError(f"Unknown generator.{name} ID(s): {', '.join(sorted(unknown))}")
    if len(set(selected)) != len(selected):
        raise ValueError(f"generator.{name} must not contain duplicates")
    return tuple(sorted(selected))


def _validate_filter(where: Mapping[str, Any], schema: RequestFeatureSchema | None) -> None:
    declared = {feature.feature_id: feature for feature in schema.features} if schema else {}
    unknown = set(where) - set(declared)
    if unknown:
        raise ValueError(f"Unknown request feature(s) in generator segment where: {', '.join(sorted(unknown))}")
    for feature_id, condition in where.items():
        capability = declared[feature_id]
        if isinstance(condition, Mapping):
            if capability.value_type != "number" or set(condition) - {"min", "max"} or not condition:
                raise ValueError(f"generator where.{feature_id} requires a numeric min/max range")
            for bound in condition.values():
                if isinstance(bound, bool) or not isinstance(bound, (int, float)) or not isfinite(bound):
                    raise ValueError(f"generator where.{feature_id} bounds must be finite numbers")
            if "min" in condition and "max" in condition and condition["min"] > condition["max"]:
                raise ValueError(f"generator where.{feature_id}.min must not exceed max")
        elif capability.value_type == "category":
            if not isinstance(condition, str):
                raise ValueError(f"generator where.{feature_id} must be a category string")
            if capability.categories and condition not in capability.categories:
                raise ValueError(f"generator where.{feature_id} has an undeclared category")
        elif capability.value_type == "number":
            if isinstance(condition, bool) or not isinstance(condition, (int, float)) or not isfinite(condition):
                raise ValueError(f"generator where.{feature_id} must be a finite number or min/max range")
        elif type(condition) is not bool:
            raise ValueError(f"generator where.{feature_id} must be a boolean")


def _matches_where(where: Mapping[str, Any], features: Mapping[str, Any],
                   schema: RequestFeatureSchema | None) -> bool:
    _validate_filter(where, schema)
    for feature_id, condition in where.items():
        value = features.get(feature_id)
        if isinstance(condition, Mapping):
            if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            if "min" in condition and value < condition["min"]:
                return False
            if "max" in condition and value > condition["max"]:
                return False
        elif value != condition:
            return False
    return True


def _rank(seed: int, segment_index: int, pair: tuple[str, str]) -> str:
    return sha256(_canonical_json([seed, segment_index, pair]).encode("utf-8")).hexdigest()


def _draw_index(seed: int, segment_index: int, draw: int, size: int) -> int:
    value = int(sha256(_canonical_json([seed, segment_index, draw]).encode("utf-8")).hexdigest(), 16)
    return value % size


def _label_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


__all__ = ["DatasetHandle", "Segment", "Workload", "generate_requests"]
