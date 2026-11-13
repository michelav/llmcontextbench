"""Helpers for sealed, provider-free benchmark artifact fixtures."""
from __future__ import annotations

import json
from pathlib import Path

from ctxbench.benchmark.execution_records import begin_attempt, finish_attempt
from ctxbench.benchmark.fingerprint import digest, file_digest, implementation_digest


def seal_benchmark_directory(
    root: Path,
    *,
    experiment_id: str,
    configurations: dict,
    surfaces: dict,
    dataset: dict | None = None,
    evaluation: dict | None = None,
    trace: dict | None = None,
) -> str:
    (root / "resolved.json").write_text("{}\n", encoding="utf-8")
    trials_path = root / "trials.jsonl"
    if not trials_path.exists():
        trials_path.write_text("", encoding="utf-8")
    dataset = dataset or {"id": "ctxbench/test", "version": "1", "contentHash": "sha256:test"}
    inputs = {
        "artifacts": {name: file_digest(root / name) for name in ("resolved.json", "trials.jsonl")},
        "implementation": implementation_digest(),
        "dataset": dataset.get("contentHash") or "sha256:test",
    }
    fingerprint = digest(inputs)
    manifest = {
        "schemaVersion": 3,
        "provisioningArtifactVersion": 4,
        "executionRecordVersion": 1,
        "experimentId": experiment_id,
        "executionFingerprint": fingerprint,
        "fingerprintInputs": inputs,
        "dataset": dataset,
        "configurations": configurations,
        "surfaces": surfaces,
        "evaluation": evaluation or {"enabled": False, "judges": []},
        "trace": trace or {"enabled": False, "writeFiles": False},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    return fingerprint


def persist_response(root: Path, trial: dict, response: dict, fingerprint: str) -> None:
    started = begin_attempt(
        root,
        trial_id=str(trial["trialId"]),
        experiment_id=str(trial["experimentId"]),
        execution_fingerprint=fingerprint,
    )
    finish_attempt(root, started, response)
