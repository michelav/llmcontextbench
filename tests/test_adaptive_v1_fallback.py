from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ctxbench.adaptive.v1 import execute_adaptive
from ctxbench.util.fs import load_json
from ctxbench.util.jsonl import read_jsonl


def _execute(tmp_path: Path, monkeypatch, results, policy=None):
    import ctxbench.benchmark.execution_records as execution_records
    import ctxbench.commands.execute as execute

    attempts = {}
    calls = []

    def durable(trials, **kwargs):
        trial = trials[0]
        calls.append(trial.trialId)
        result = results[trial.trialId]
        attempts.setdefault(trial.trialId, []).append({
            "state": result["recordState"], "attemptId": f"{trial.trialId}-attempt",
            "result": result["result"],
        })

    monkeypatch.setattr(execute, "_execute_durable", durable)
    monkeypatch.setattr(execute, "_latest_attempt", lambda rows: rows[-1] if rows else None)
    monkeypatch.setattr(execution_records, "attempts_for_trial", lambda _root, tid: attempts.get(tid, []))
    run_specs = [SimpleNamespace(trialId="trial-a"), SimpleNamespace(trialId="trial-b")]
    plan = {"policy": policy or {"type": "cascade", "candidate": ["m", "a"],
                                 "fallbacks": [["m", "b"]], "minimumResponseLength": 3},
            "workload": [{"requestId": "request-000001", "sequenceIndex": 1,
                          "taskId": "task", "instanceId": "instance", "sizeBin": "small",
                          "phase": "default", "toolDelayMs": 0,
                          "candidates": {"m/a": "trial-a", "m/b": "trial-b"}}]}
    execute_adaptive(plan, None, run_specs, root=tmp_path,
                     manifest={"executionFingerprint": "fingerprint"}, force=False,
                     retry_uncertain=False, logger=None, progress=False)
    return calls, load_json(tmp_path / "adaptive-records/request-000001.json"), read_jsonl(tmp_path / "requests.jsonl")


def _result(status="success", response="accepted", total=10, known=10, duration=5):
    return {"recordState": "succeeded" if status == "success" else "failed",
            "result": {"status": status, "response": response,
                       "timing": {"durationMs": duration},
                       "metricsSummary": {"totalTokens": total, "knownTotalTokens": known}}}


def test_failure_then_success_delivers_fallback_and_sums_usage(tmp_path, monkeypatch):
    calls, record, rows = _execute(tmp_path, monkeypatch, {
        "trial-a": _result("error", "", total=None, known=4, duration=7),
        "trial-b": _result("success", "good answer", total=11, known=11, duration=9),
    })
    assert calls == ["trial-a", "trial-b"]
    assert record["state"] == "delivered"
    assert record["delivery"]["candidate"] == "m/b"
    assert record["totalTokens"] is None and record["knownTotalTokens"] == 15
    assert record["durationMs"] == 16 and record["usageCompleteness"] == "partial"
    assert [row["accepted"] for row in record["attempts"]] == [False, True]
    assert rows[0]["state"] == "delivered"


def test_sensor_rejection_triggers_fallback_and_only_fallback_is_delivered(tmp_path, monkeypatch):
    calls, record, _ = _execute(tmp_path, monkeypatch, {
        "trial-a": _result(response="no"), "trial-b": _result(response="long enough"),
    })
    assert calls == ["trial-a", "trial-b"]
    assert record["attempts"][0]["status"] == "success"
    assert record["attempts"][0]["accepted"] is False
    assert record["delivery"]["candidate"] == "m/b"


def test_candidate_exhaustion_records_failed_request_and_all_attempts(tmp_path, monkeypatch):
    calls, record, _ = _execute(tmp_path, monkeypatch, {
        "trial-a": _result("error", "", total=None, known=None),
        "trial-b": _result("error", "", total=None, known=None),
    })
    assert calls == ["trial-a", "trial-b"]
    assert record["state"] == "failed" and record["delivery"] is None
    assert len(record["attempts"]) == 2
    assert record["totalTokens"] is None and record["knownTotalTokens"] is None


def test_interruption_leaves_request_started_and_never_marks_delivery(tmp_path, monkeypatch):
    import ctxbench.benchmark.execution_records as execution_records
    import ctxbench.commands.execute as execute

    attempts = {}
    monkeypatch.setattr(execute, "_latest_attempt", lambda rows: rows[-1] if rows else None)
    monkeypatch.setattr(execution_records, "attempts_for_trial", lambda _root, tid: attempts.get(tid, []))
    run_specs = [SimpleNamespace(trialId="trial-a"), SimpleNamespace(trialId="trial-b")]
    plan = {"policy": {"type": "cascade", "candidate": ["m", "a"], "fallbacks": [["m", "b"]]},
            "workload": [{"requestId": "request-000001", "sequenceIndex": 1,
                          "taskId": "task", "instanceId": "instance", "sizeBin": "small",
                          "phase": "default", "toolDelayMs": 0,
                          "candidates": {"m/a": "trial-a", "m/b": "trial-b"}}]}
    def interrupt(trials, **_kwargs):
        attempts[trials[0].trialId] = [{"state": "started", "attemptId": "uncertain"}]
        raise KeyboardInterrupt

    monkeypatch.setattr(execute, "_execute_durable", interrupt)
    with pytest.raises(KeyboardInterrupt):
        execute_adaptive(plan, None, run_specs, root=tmp_path,
                         manifest={"executionFingerprint": "fingerprint"}, force=False,
                         retry_uncertain=False, logger=None, progress=False)
    record = load_json(tmp_path / "adaptive-records/request-000001.json")
    assert record["state"] == "started" and record["delivery"] is None

    monkeypatch.setattr(execute, "_execute_durable", lambda *_args, **_kwargs: pytest.fail("must not rerun uncertain"))
    with pytest.raises(ValueError, match="uncertain attempt"):
        execute_adaptive(plan, None, run_specs, root=tmp_path,
                         manifest={"executionFingerprint": "fingerprint"}, force=False,
                         retry_uncertain=False, logger=None, progress=False)
    record = load_json(tmp_path / "adaptive-records/request-000001.json")
    assert record["state"] == "started" and record["delivery"] is None
