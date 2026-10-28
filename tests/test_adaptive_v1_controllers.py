from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ctxbench.adaptive.v1 import (
    DelayedToolRuntime, TokenQuota, _validate_phases, build_adaptive_plan, choose_candidate,
)


REQUEST = {"requestId": "request-000001", "sizeBin": "small",
           "candidates": {"m/a": "a", "m/b": "b"}}


def test_utility_requires_known_metrics_and_ranks_weighted_cost():
    policy = {"type": "utility", "latencyWeight": 1, "tokenWeight": 0.1}
    estimates = {"m/a|small": {"latencyMs": 100, "totalTokens": 100},
                 "m/b|small": {"latencyMs": 50, "totalTokens": 1000}}
    assert choose_candidate({"policy": policy}, REQUEST, {"estimates": estimates}) == ("m/a", "minimum_weighted_cost")
    assert choose_candidate({"policy": policy}, REQUEST, {"estimates": {}}) == (None, "unknown_utility_estimate")


def test_circuit_breaker_routes_to_fallback_after_failure_window():
    plan = {"policy": {"type": "circuit_breaker", "candidate": ["m", "a"],
                       "fallbacks": [["m", "b"]], "window": 3,
                       "minimumObservations": 2, "failureRateThreshold": 0.5}}
    history = {"m/a": [{"status": "error"}, {"status": "success"}, {"status": "error"}]}
    assert choose_candidate(plan, REQUEST, None, history=history) == ("m/b", "circuit_open")


def test_seeded_exploration_is_stable_for_request_identity():
    policy = {"type": "explore", "seed": 29, "explorationProbability": 1,
              "latencyWeight": 1, "tokenWeight": 1}
    knowledge = {"estimates": {"m/a|small": {"latencyMs": 10, "totalTokens": 10},
                                "m/b|small": {"latencyMs": 20, "totalTokens": 20}}}
    first = choose_candidate({"policy": policy}, REQUEST, knowledge)
    assert first == choose_candidate({"policy": policy}, REQUEST, knowledge)
    assert first[0] in REQUEST["candidates"] and first[1] == "seeded_exploration"


def test_budget_unknown_estimates_reject_unless_best_effort():
    estimates = {"m/a|small": {"totalTokens": None}, "m/b|small": {"totalTokens": 12}}
    strict = {"policy": {"type": "budget", "tokenBudget": 50}}
    best_effort = {"policy": {"type": "budget", "tokenBudget": 50, "bestEffort": True}}
    assert choose_candidate(strict, REQUEST, {"estimates": estimates}) == ("m/b", "budget_admitted")
    assert choose_candidate(strict, REQUEST, {"estimates": estimates}, unknown_spend=True) == (None, "unknown_consumption")
    assert choose_candidate(best_effort, REQUEST, {"estimates": {}}, unknown_spend=True) == ("m/a", "budget_best_effort")


def test_quota_restores_recent_usage_and_waits_until_it_expires():
    class Clock:
        now = 100.0
        def __call__(self): return self.now
        def sleep(self, delay): self.now += delay

    clock = Clock()
    stamp = datetime.fromtimestamp(70, timezone.utc).isoformat()
    saved = [{"attempts": [{"quotaTimestamp": stamp, "totalTokens": 8}]}]
    quota = TokenQuota({"tokens": 10, "windowSeconds": 60}, saved,
                       clock=clock, sleeper=clock.sleep, monotonic_clock=clock)
    waited = quota.wait_for_capacity(5)
    assert 29_999 <= waited <= 30_001
    assert quota.rows == []


def test_quota_unknown_usage_blocks_unless_best_effort():
    saved = [{"attempts": [{"quotaTimestamp": "2026-01-01T00:00:00+00:00",
                            "totalTokens": None, "knownTotalTokens": 3}]}]
    strict = TokenQuota({"tokens": 10, "windowSeconds": 60}, saved)
    permissive = TokenQuota({"tokens": 10, "windowSeconds": 60, "bestEffort": True}, saved)
    assert strict.rows[0][1] == 3
    assert strict.wait_for_capacity(2) is None
    assert permissive.wait_for_capacity(None) == 0


def test_seeded_tool_failure_disturbance_replays_exactly():
    class Runtime:
        def call_tool(self, name, arguments): return "ok"
        def list_tools(self): return []
        def close(self): pass

    def outcomes():
        runtime = DelayedToolRuntime(Runtime(), 0, failure_rate=0.5, failure_seed=71)
        result = []
        for index in range(20):
            try:
                runtime.call_tool("lookup", {"index": index})
                result.append(False)
            except RuntimeError:
                result.append(True)
        return result

    assert outcomes() == outcomes()
    assert 0 < sum(outcomes()) < 20


def test_tool_failure_phase_requires_seed_and_valid_probability():
    phase = {"name": "fault", "firstRequest": 1, "lastRequest": 1,
             "toolFailureRate": 0.2, "failureSeed": 42}
    assert _validate_phases([phase], 1)[0]["failureSeed"] == 42
    with pytest.raises(ValueError, match="delay/fault"):
        _validate_phases([{**phase, "failureSeed": None}], 1)
    with pytest.raises(ValueError, match="delay/fault"):
        _validate_phases([{**phase, "toolFailureRate": 1.1}], 1)


def test_best_effort_quota_is_frozen_into_adaptive_plan():
    dataset = SimpleNamespace(list_task_ids=lambda: ["task"], list_instance_ids=lambda: ["instance"],
                              request_features=lambda *_args: {"sizeBin": "small"})
    trial = SimpleNamespace(repeatIndex=1, taskId="task", instanceId="instance",
                            modelId="m", configurationId="a", trialId="trial")
    plan, knowledge = build_adaptive_plan({
        "policy": {"type": "static", "candidate": ["m", "a"]},
        "tokenQuota": {"tokens": 100, "windowSeconds": 60, "bestEffort": True},
        "workload": [{"taskId": "task", "instanceId": "instance"}],
    }, [trial], dataset)
    assert plan["tokenQuota"] == {"tokens": 100, "windowSeconds": 60, "bestEffort": True}
    assert knowledge is None
    with pytest.raises(ValueError, match="calibration run"):
        build_adaptive_plan({"policy": {"type": "static", "candidate": ["m", "a"]},
                             "tokenQuota": {"tokens": 100, "windowSeconds": 60},
                             "workload": [{"taskId": "task", "instanceId": "instance"}]},
                            [trial], dataset)
