"""Canonical per-attempt records for version-4 static executions."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
from pathlib import Path
from typing import Any, Iterator

from ctxbench.util.clock import utc_now_iso
from ctxbench.util.fs import load_json, write_json
from ctxbench.util.jsonl import read_jsonl, write_jsonl

RECORDS_DIRECTORY = "execution-records"
RECORD_VERSION = 1


@contextmanager
def execution_lock(root: str | Path, *, wait: bool = False) -> Iterator[None]:
    """Hold one advisory writer lock for the artifact directory."""
    lock_path = Path(root) / ".execute.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        flags = fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(handle.fileno(), flags)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another execution writer holds {lock_path}.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def attempts_for_trial(root: str | Path, trial_id: str) -> list[dict[str, Any]]:
    directory = _trial_directory(root, trial_id)
    if not directory.exists():
        return []
    attempts: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for path in sorted(directory.glob("attempt-*.json")):
        try:
            record = load_json(path)
        except Exception as exc:
            raise ValueError(f"Invalid execution record {path}: {exc}") from exc
        _validate_record(record, path, trial_id)
        index = record["attemptIndex"]
        if index in seen_indices:
            raise ValueError(f"Duplicate attemptIndex {index} for trialId {trial_id}.")
        seen_indices.add(index)
        attempts.append(record)
    return sorted(attempts, key=lambda item: item["attemptIndex"])


def latest_attempt(root: str | Path, trial_id: str) -> dict[str, Any] | None:
    attempts = attempts_for_trial(root, trial_id)
    return attempts[-1] if attempts else None


def begin_attempt(
    root: str | Path,
    *,
    trial_id: str,
    experiment_id: str,
    execution_fingerprint: str,
) -> dict[str, Any]:
    attempts = attempts_for_trial(root, trial_id)
    index = attempts[-1]["attemptIndex"] + 1 if attempts else 1
    record = {
        "executionRecordVersion": RECORD_VERSION,
        "trialId": trial_id,
        "experimentId": experiment_id,
        "attemptId": f"{_trial_key(trial_id)[:16]}-{index:06d}",
        "attemptIndex": index,
        "executionFingerprint": execution_fingerprint,
        "state": "started",
        "startedAt": utc_now_iso(),
    }
    write_json(_trial_directory(root, trial_id) / f"attempt-{index:06d}.json", record)
    return record


def finish_attempt(root: str | Path, record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if result.get("trialId") != record.get("trialId"):
        raise ValueError("Execution result trialId does not match its attempt record.")
    finished = {
        **record,
        "state": "succeeded" if result.get("status") == "success" else "failed",
        "finishedAt": utc_now_iso(),
        "result": result,
    }
    path = _trial_directory(root, str(record["trialId"])) / f"attempt-{record['attemptIndex']:06d}.json"
    write_json(path, finished)
    return finished


def rebuild_responses(root: str | Path, *, execution_fingerprint: str) -> list[dict[str, Any]]:
    """Rebuild the derived response collection from the latest terminal attempts."""
    artifact_root = Path(root)
    trials_path = artifact_root / "trials.jsonl"
    trials = read_jsonl(trials_path) if trials_path.exists() else []
    by_id: dict[str, dict[str, Any]] = {}
    for trial in trials:
        trial_id = str(trial.get("trialId") or "")
        if not trial_id or trial_id in by_id:
            raise ValueError(f"Missing or duplicate trialId in {trials_path}: {trial_id!r}")
        by_id[trial_id] = trial

    records_root = artifact_root / RECORDS_DIRECTORY
    responses: list[dict[str, Any]] = []
    latest_by_trial: dict[str, dict[str, Any]] = {}
    if records_root.exists():
        for directory in sorted(path for path in records_root.iterdir() if path.is_dir()):
            for path in sorted(directory.glob("attempt-*.json")):
                try:
                    record = load_json(path)
                except Exception as exc:
                    raise ValueError(f"Invalid execution record {path}: {exc}") from exc
                trial_id = str(record.get("trialId") or "") if isinstance(record, dict) else ""
                if trial_id not in by_id:
                    raise ValueError(f"Execution record references unknown trialId in {path}: {trial_id!r}")
                if record.get("experimentId") != by_id[trial_id].get("experimentId"):
                    raise ValueError(f"Execution record experimentId mismatch in {path}")
                if _trial_directory(artifact_root, trial_id) != directory:
                    raise ValueError(f"Execution record is stored under the wrong trial key: {path}")
                _validate_record(record, path, trial_id)
                if record.get("executionFingerprint") != execution_fingerprint:
                    raise ValueError(f"Execution fingerprint mismatch in {path}")
                current = latest_by_trial.get(trial_id)
                if current is None or record["attemptIndex"] > current["attemptIndex"]:
                    latest_by_trial[trial_id] = record

    for trial in trials:
        trial_id = str(trial["trialId"])
        latest = latest_by_trial.get(trial_id)
        if latest is None or latest["state"] == "started":
            continue
        result = latest.get("result")
        if not isinstance(result, dict):
            raise ValueError(f"Completed execution record has no result for trialId {trial_id}")
        responses.append(result)

    write_jsonl(artifact_root / "responses.jsonl", responses)
    return responses


def latest_attempt_states(root: str | Path) -> dict[str, str]:
    trials_path = Path(root) / "trials.jsonl"
    trials = read_jsonl(trials_path) if trials_path.exists() else []
    states: dict[str, str] = {}
    for trial in trials:
        trial_id = str(trial.get("trialId") or "")
        latest = latest_attempt(root, trial_id) if trial_id else None
        if latest is not None:
            states[trial_id] = str(latest["state"])
    return states


def _validate_record(record: Any, path: Path, trial_id: str) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"Invalid execution record {path}: expected an object")
    if type(record.get("executionRecordVersion")) is not int or record["executionRecordVersion"] != RECORD_VERSION:
        raise ValueError(f"Unsupported execution record version in {path}")
    if record.get("trialId") != trial_id:
        raise ValueError(f"Execution record trialId mismatch in {path}")
    if not isinstance(record.get("experimentId"), str) or not record["experimentId"]:
        raise ValueError(f"Missing experimentId in {path}")
    index = record.get("attemptIndex")
    if type(index) is not int or index < 1 or path.name != f"attempt-{index:06d}.json":
        raise ValueError(f"Invalid attemptIndex in {path}")
    if record.get("state") not in {"started", "succeeded", "failed"}:
        raise ValueError(f"Invalid execution state in {path}")
    if not isinstance(record.get("executionFingerprint"), str) or not record["executionFingerprint"]:
        raise ValueError(f"Missing execution fingerprint in {path}")
    expected_attempt_id = f"{_trial_key(trial_id)[:16]}-{index:06d}"
    if record.get("attemptId") != expected_attempt_id:
        raise ValueError(f"Invalid attemptId in {path}")
    if not isinstance(record.get("startedAt"), str) or not record["startedAt"]:
        raise ValueError(f"Missing startedAt in {path}")
    if record["state"] == "started" and "result" in record:
        raise ValueError(f"Started execution record unexpectedly has a result: {path}")
    if record["state"] in {"succeeded", "failed"}:
        if not isinstance(record.get("finishedAt"), str) or not record["finishedAt"]:
            raise ValueError(f"Missing finishedAt in {path}")
        if not isinstance(record.get("result"), dict):
            raise ValueError(f"Completed execution record has no result: {path}")
        if record["result"].get("trialId") != trial_id:
            raise ValueError(f"Execution result trialId mismatch in {path}")
        if record["result"].get("experimentId") != record["experimentId"]:
            raise ValueError(f"Execution result experimentId mismatch in {path}")
        expected = "success" if record["state"] == "succeeded" else "error"
        if record["result"].get("status") != expected:
            raise ValueError(f"Execution state/result status mismatch in {path}")


def _trial_directory(root: str | Path, trial_id: str) -> Path:
    return Path(root) / RECORDS_DIRECTORY / _trial_key(trial_id)


def _trial_key(trial_id: str) -> str:
    return hashlib.sha256(trial_id.encode("utf-8")).hexdigest()[:24]
