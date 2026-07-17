from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ctxbench.util.jsonl import read_jsonl
from ctxbench.util.logging import PhaseLogger


@dataclass(frozen=True)
class ExperimentArtifacts:
    root: Path
    manifest: dict[str, Any] | None
    trials: list[dict[str, Any]]
    responses: list[dict[str, Any]]
    evals: list[dict[str, Any]]
    votes: list[dict[str, Any]]


def load_inputs(inputs: list[str], logger: PhaseLogger) -> list[ExperimentArtifacts]:
    roots = [Path(item).expanduser() for item in inputs]
    valid: list[ExperimentArtifacts] = []
    for root in roots:
        trials_path = root / "trials.jsonl"
        if not trials_path.exists():
            message = f"Missing required artifact: {trials_path}"
            if len(roots) == 1:
                raise ValueError(message)
            logger.warn("METRICS", "metrics.input.skipped", message, experimentDir=str(root))
            continue
        manifest = _load_json(root / "manifest.json")
        if manifest is None:
            logger.warn(
                "METRICS",
                "metrics.manifest.missing",
                "manifest.json missing; continuing with artifact fields",
                experimentDir=str(root),
            )
        valid.append(
            ExperimentArtifacts(
                root=root,
                manifest=manifest,
                trials=read_jsonl(trials_path),
                responses=_read_optional_jsonl(root / "responses.jsonl"),
                evals=_read_optional_jsonl(root / "evals.jsonl"),
                votes=_read_optional_jsonl(root / "judge_votes.jsonl"),
            )
        )
    if not valid:
        raise ValueError("No valid input directories with trials.jsonl remain.")
    _validate_unique_trial_ids(valid)
    return valid


def index_latest(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        trial_id = row.get("trialId")
        if trial_id:
            index[str(trial_id)] = row
    return index


def index_votes(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        trial_id = row.get("trialId")
        if trial_id:
            index.setdefault(str(trial_id), []).append(row)
    return index


def load_trace(root: Path, trace_ref: Any, fallback: Path) -> dict[str, Any] | None:
    candidates: list[Path] = []
    if isinstance(trace_ref, str) and trace_ref.strip():
        ref = Path(trace_ref)
        candidates.append(ref if ref.is_absolute() else root / ref)
    candidates.append(fallback)
    for path in candidates:
        if path.exists() and path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
            return payload if isinstance(payload, dict) else None
    return None


def _read_optional_jsonl(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path) if path.exists() else []


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _validate_unique_trial_ids(inputs: list[ExperimentArtifacts]) -> None:
    seen: dict[str, Path] = {}
    for artifacts in inputs:
        local: set[str] = set()
        for row in artifacts.trials:
            trial_id = row.get("trialId")
            if not trial_id:
                continue
            trial_id = str(trial_id)
            if trial_id in local:
                raise ValueError(f"Duplicate trialId in {artifacts.root / 'trials.jsonl'}: {trial_id}")
            local.add(trial_id)
            previous = seen.get(trial_id)
            if previous is not None:
                raise ValueError(
                    f"Duplicate trialId across input directories: {trial_id} "
                    f"({previous} and {artifacts.root})"
                )
            seen[trial_id] = artifacts.root

