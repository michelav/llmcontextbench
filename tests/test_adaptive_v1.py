from __future__ import annotations

from ctxbench.adaptive.v1 import DelayedToolRuntime, choose_candidate
from ctxbench.adaptive.v1 import _load_calibration
from ctxbench.util.jsonl import write_jsonl
import json
from types import SimpleNamespace
import pytest


def test_threshold_selection_is_deterministic_and_prefers_tokens_under_target():
    plan = {"policy": {"type": "threshold", "latencyTargetMs": 120}}
    request = {"sizeBin": "small", "candidates": {"m/a": "t1", "m/b": "t2"}}
    knowledge = {"estimates": {
        "m/a|small": {"latencyMs": 100, "totalTokens": 500},
        "m/b|small": {"latencyMs": 110, "totalTokens": 200},
    }}
    assert choose_candidate(plan, request, knowledge) == ("m/b", "threshold")


def test_threshold_falls_back_to_fastest_when_latency_target_is_missed():
    plan = {"policy": {"type": "threshold", "latencyTargetMs": 50}}
    request = {"sizeBin": "small", "candidates": {"m/a": "t1", "m/b": "t2"}}
    knowledge = {"estimates": {
        "m/a|small": {"latencyMs": 100, "totalTokens": 500},
        "m/b|small": {"latencyMs": 80, "totalTokens": 900},
    }}
    assert choose_candidate(plan, request, knowledge) == ("m/b", "threshold")


def test_request_rejects_when_no_candidate_is_eligible():
    plan = {"policy": {"type": "static", "candidate": ["m", "a"]}}
    assert choose_candidate(plan, {"candidates": {}}, None) == (None, "no_eligible_candidate")


def test_delayed_tool_runtime_injects_one_delay_per_call():
    class Runtime:
        def list_tools(self): return []
        def call_tool(self, name, arguments): return (name, arguments)
        def close(self): self.closed = True

    waits, inner = [], Runtime()
    wrapped = DelayedToolRuntime(inner, 25, sleeper=waits.append)
    assert wrapped.call_tool("lookup", {"id": 1}) == ("lookup", {"id": 1})
    wrapped.close()
    assert waits == [0.025]
    assert inner.closed


def test_calibration_derives_metrics_and_rejects_workload_leakage(tmp_path, monkeypatch):
    import ctxbench.adaptive.v1 as adaptive

    (tmp_path / "manifest.json").write_text(json.dumps({
        "experimentKind": "benchmark", "evaluation": {"enabled": False},
        "dataset": {"id": "fake"},
    }))
    write_jsonl(tmp_path / "responses.jsonl", [{
        "taskId": "task_role", "instanceId": "calibration-instance", "modelId": "m",
        "configurationId": "c", "status": "success",
        "timing": {"durationMs": 10}, "metricsSummary": {"totalTokens": 20},
    }])
    monkeypatch.setattr(adaptive, "validate_artifact_directory", lambda _root: json.loads((tmp_path / "manifest.json").read_text()))
    trial = SimpleNamespace(modelId="m", configurationId="c", dataset=SimpleNamespace(id="fake"))
    dataset = SimpleNamespace(request_features=lambda _instance, _task: {"sizeBin": "small"})
    workload = [{"taskId": "task_role", "instanceId": "evaluation-instance", "sizeBin": "small",
                 "candidates": {"m/c": "trial"}}]
    result = _load_calibration(str(tmp_path), [trial], workload, dataset)
    estimate = result["estimates"]["m/c|small"]
    assert estimate["latencyMs"] == 10
    assert estimate["totalTokens"] == 20
    assert estimate["provenance"] == "derived"

    workload[0]["instanceId"] = "calibration-instance"
    with pytest.raises(ValueError, match="overlap"):
        _load_calibration(str(tmp_path), [trial], workload, dataset)
