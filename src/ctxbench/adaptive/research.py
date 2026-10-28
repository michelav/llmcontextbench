"""Small, provider-free helpers for preparing and comparing adaptive studies.

Resampled values are explicitly estimated. Dataset derivation copies a complete
source tree and records the selected request set; adapters remain responsible
for interpreting that manifest and enforcing domain-specific lineage rules.
"""
from __future__ import annotations

import json
import random
import shutil
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Iterable


def seeded_workload(requests: Iterable[dict], *, size: int, seed: int,
                    excluded_groups: set[str] | None = None) -> list[dict]:
    """Sample requests without replacement, excluding any declared source group."""
    rows = list(requests)
    if type(size) is not int or size < 1 or type(seed) is not int:
        raise ValueError("size must be positive and seed must be an integer")
    groups = defaultdict(list)
    for row in rows:
        key = (row.get("taskId"), row.get("instanceId"))
        group = row.get("sourceGroup")
        if not all(isinstance(part, str) and part for part in key):
            raise ValueError("workload rows require taskId and instanceId")
        if group is not None and not isinstance(group, str):
            raise ValueError("sourceGroup must be a string when provided")
        groups[key].append(row)
    if any(len(members) > 1 for members in groups.values()):
        raise ValueError("workload contains duplicate taskId/instanceId pairs")
    eligible = [row for row in rows if row.get("sourceGroup") not in (excluded_groups or set())]
    if size > len(eligible):
        raise ValueError("requested workload exceeds eligible coverage")
    return random.Random(seed).sample(eligible, size)


def resample_knowledge(observations: Iterable[dict], *, candidates: Iterable[str],
                       feature_groups: Iterable[str], replicates: int, seed: int) -> dict:
    """Bootstrap candidate/feature metric observations with deterministic streams."""
    if type(replicates) is not int or replicates < 1 or type(seed) is not int:
        raise ValueError("replicates must be positive and seed must be an integer")
    grouped = defaultdict(list)
    for row in observations:
        candidate, feature = row.get("candidateId"), row.get("featureGroup")
        if isinstance(candidate, str) and isinstance(feature, str):
            grouped[(candidate, feature)].append(row)
    result = {}
    for candidate in sorted(set(candidates)):
        for feature in sorted(set(feature_groups)):
            source = grouped.get((candidate, feature), [])
            if not source:
                raise ValueError(f"missing calibration coverage for {candidate} / {feature}")
            rng = random.Random(f"{seed}:{candidate}:{feature}")
            metrics = sorted({key for row in source for key, value in row.items()
                              if key not in {"candidateId", "featureGroup"}
                              and isinstance(value, (int, float)) and not isinstance(value, bool)})
            result[f"{candidate}|{feature}"] = {
                metric: {"samples": [mean(rng.choices([r[metric] for r in source if metric in r],
                                                       k=sum(metric in r for r in source)))
                                     for _ in range(replicates)], "provenance": "estimated"}
                for metric in metrics if any(metric in row for row in source)
            }
    return {"schemaVersion": 1, "seed": seed, "replicates": replicates, "estimates": result}


def knowledge_diff(before: dict, after: dict) -> list[dict]:
    """Return sorted changes in knowledge estimates without mutating snapshots."""
    left, right = before.get("estimates", {}), after.get("estimates", {})
    changes = []
    for key in sorted(set(left) | set(right)):
        for metric in sorted(set(left.get(key, {})) | set(right.get(key, {}))):
            a, b = left.get(key, {}).get(metric), right.get(key, {}).get(metric)
            if a != b:
                changes.append({"key": key, "metric": metric, "before": a, "after": b})
    return changes


def materialize_derivation(source: str | Path, destination: str | Path, *,
                           dataset_id: str, selected_requests: Iterable[dict]) -> dict:
    """Copy a dataset tree and add provenance; source data is never modified."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir() or source == destination or source in destination.parents:
        raise ValueError("destination must be outside the source dataset tree")
    if destination.exists():
        raise FileExistsError(destination)
    requests = list(selected_requests)
    if len({(r.get("taskId"), r.get("instanceId")) for r in requests}) != len(requests):
        raise ValueError("selected requests contain duplicate task/instance pairs")
    shutil.copytree(source, destination)
    manifest = {"schemaVersion": 1, "derivedFrom": str(source), "datasetId": dataset_id,
                "selectedRequests": requests, "provenance": "derived"}
    (destination / "derivation.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def paired_differences(rows: Iterable[dict], *, metric: str, left: str, right: str,
                       pair_key: str = "requestId") -> dict:
    """Summarize paired right-minus-left differences and report incomplete coverage."""
    pairs = defaultdict(dict)
    for row in rows:
        pair, arm, value = row.get(pair_key), row.get("arm"), row.get(metric)
        if pair is None or arm not in {left, right} or not isinstance(value, (int, float)):
            continue
        if arm in pairs[pair]:
            raise ValueError(f"duplicate arm observation for {pair}")
        pairs[pair][arm] = value
    complete = [(key, value[right] - value[left]) for key, value in sorted(pairs.items())
                if left in value and right in value]
    return {"metric": metric, "left": left, "right": right, "pairedCount": len(complete),
            "scheduledPairs": len(pairs), "coverage": len(complete) / len(pairs) if pairs else 0.0,
            "meanDifference": mean(value for _, value in complete) if complete else None,
            "differences": [{"pair": key, "difference": value} for key, value in complete],
            "provenance": "derived"}
