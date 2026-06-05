from __future__ import annotations

import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ctxbench.metrics.aggregate import (
    AGGREGATE_FIELDS,
    EFFECTIVENESS_FIELDS,
    EFFICIENCY_FIELDS,
    EVALUATION_RELIABILITY_FIELDS,
    OBSERVABILITY_FIELDS,
    ROBUSTNESS_FIELDS,
)
from ctxbench.metrics.io import ExperimentArtifacts
from ctxbench.metrics.trial_rows import TRIAL_FIELDS
from ctxbench.util.fs import write_text_atomic


OUTPUTS = [
    "trial_metrics.csv",
    "aggregate_metrics.csv",
    "dimension_summary.csv",
    "summary.json",
    "failure_cases.csv",
    "dimensions/effectiveness.csv",
    "dimensions/efficiency.csv",
    "dimensions/robustness.csv",
    "dimensions/evaluation_reliability.csv",
    "dimensions/observability.csv",
]
FAILURE_FIELDS = [
    "dataset_id", "experimentId", "trialId", "taskId", "instanceId", "modelId", "configuration",
    "execution_status", "evaluation_status", "evaluation_method", "primary_metric_name",
    "primary_success", "primary_score", "error_message", "response_excerpt",
]


def prepare_output_dir(path: Path, *, force: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not force:
            raise ValueError(f"Output directory exists and is non-empty: {path}. Use --force to replace it.")
        if path.name != "metrics" and not path.is_dir():
            raise ValueError(f"Refusing to replace non-directory output path: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    (path / "dimensions").mkdir(parents=True, exist_ok=True)


def write_outputs(
    output_dir: Path,
    *,
    group_fields: list[str],
    trial_rows: list[dict[str, Any]],
    metrics: dict[str, Any],
    failure_rows: list[dict[str, Any]],
    inputs: list[ExperimentArtifacts],
    selectors: dict[str, Any],
    command: str,
) -> None:
    write_csv(output_dir / "trial_metrics.csv", TRIAL_FIELDS, trial_rows)
    write_csv(output_dir / "dimensions" / "effectiveness.csv", [*group_fields, *EFFECTIVENESS_FIELDS], metrics["effectiveness"])
    write_csv(output_dir / "dimensions" / "efficiency.csv", [*group_fields, *EFFICIENCY_FIELDS], metrics["efficiency"])
    write_csv(output_dir / "dimensions" / "robustness.csv", [*group_fields, *ROBUSTNESS_FIELDS], metrics["robustness"])
    write_csv(output_dir / "dimensions" / "evaluation_reliability.csv", [*group_fields, *EVALUATION_RELIABILITY_FIELDS], metrics["evaluation_reliability"])
    write_csv(output_dir / "dimensions" / "observability.csv", [*group_fields, *OBSERVABILITY_FIELDS], metrics["observability"])
    write_csv(output_dir / "aggregate_metrics.csv", [*group_fields, *AGGREGATE_FIELDS], metrics["aggregate"])
    write_csv(output_dir / "dimension_summary.csv", ["dimension", "group_key", *group_fields, "metric", "value"], metrics["dimension_summary"])
    write_csv(output_dir / "failure_cases.csv", FAILURE_FIELDS, failure_rows)
    write_json(output_dir / "summary.json", metrics["summary"])
    write_json(output_dir / "metrics-manifest.json", _manifest(inputs, selectors, group_fields, command))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text_atomic(path, json.dumps(_json_value(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _manifest(inputs: list[ExperimentArtifacts], selectors: dict[str, Any], group_fields: list[str], command: str) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "command": command,
        "metricFramework": {
            "inspiredBy": "HELM",
            "coreDimensions": [
                "effectiveness",
                "efficiency",
                "robustness",
                "evaluation_reliability",
                "observability",
            ],
        },
        "selectors": selectors,
        "groupBy": group_fields,
        "inputs": [_input_manifest(item) for item in inputs],
        "outputs": OUTPUTS,
    }


def _input_manifest(item: ExperimentArtifacts) -> dict[str, Any]:
    first = item.trials[0] if item.trials else {}
    dataset = first.get("dataset") if isinstance(first.get("dataset"), dict) else {}
    manifest_dataset = (item.manifest or {}).get("dataset") if isinstance((item.manifest or {}).get("dataset"), dict) else {}
    return {
        "experimentDir": str(item.root),
        "experimentId": first.get("experimentId") or (item.manifest or {}).get("experimentId"),
        "datasetId": dataset.get("id") or manifest_dataset.get("id"),
        "datasetVersion": dataset.get("version") or manifest_dataset.get("version"),
        "datasetContentHash": manifest_dataset.get("contentHash") or manifest_dataset.get("content_hash"),
        "datasetResolvedRevision": manifest_dataset.get("resolvedRevision") or manifest_dataset.get("resolved_revision"),
        "trials": len(item.trials),
        "responses": len(item.responses),
        "evaluations": len(item.evals),
        "judgeVotes": len(item.votes),
    }


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _format_float(value)
    return str(value)


def _format_float(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.6g}"


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value

