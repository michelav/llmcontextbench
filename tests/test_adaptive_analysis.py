"""WP-H gate: goals, adaptive metric columns, summarize and headroom (provider-free)."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ctxbench.adaptive.goals import evaluate_goals
from ctxbench.adaptive.state import WindowSpec
from ctxbench.api import headroom, open_run, plan, summarize
from ctxbench.metrics.adaptive import build_adaptive_goal_metrics
from ctxbench.util.fs import load_json

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "tests/fixtures/fake_dataset/dataset"


def _definition(*, request_count: int = 1) -> dict:
    value = json.loads((ROOT / "examples/adaptive/minimal.json").read_text(encoding="utf-8"))
    value["dataset"]["root"] = str(DATASET.resolve())
    value["candidates"] = {"A": {"model": "mock", "configuration": "inline-json"},
                           "B": {"model": "mock", "configuration": "inline-json"}}
    value["workload"]["requests"] = [
        {"requestId": f"r-{index:04}", "taskId": "task_role", "instanceId": "person-001",
         "labels": {"position": str(index)}}
        for index in range(1, request_count + 1)
    ]
    value["policy"] = {"ref": "static", "params": {"candidate": "A"}}
    return value


# --- goals ------------------------------------------------------------------------------------

def _record(sequence: int, candidate: str, signals: dict[str, float | None], *, state: str = "delivered") -> dict:
    return {
        "requestId": f"r-{sequence:04d}", "sequenceIndex": sequence, "state": state,
        "attempts": [{
            "decision": {"candidateId": candidate},
            "observation": {
                "status": "success" if state == "delivered" else "error",
                "failureCategory": None if state == "delivered" else "provider_error",
                "signals": {name: {"value": value, "unit": "tokens",
                                   "provenance": "reported" if value is not None else "unavailable"}
                            for name, value in signals.items()},
                "knownSubtotals": {},
            },
        }],
    }


TOKENS = [10, 20, 30, 40, 50]
RECORDS = [_record(index, "A" if index % 2 else "B", {"total_tokens": value})
           for index, value in enumerate(TOKENS, start=1)]


def _statuses(goal: dict, records=RECORDS, default=WindowSpec(2, "sliding")) -> list[tuple]:
    rows = evaluate_goals(records, [goal], candidates=["A", "B"], signals=(), default_window=default)
    return [(row["sequenceIndex"], row["value"], row["status"], row["sampleCount"]) for row in rows]


def test_goal_fixed_window_includes_each_request_and_resets_per_block() -> None:
    # Blocks of 2: {1,2}, {3,4}, {5}; each reading ends with the evaluated request.
    goal = {"id": "budget", "signal": "total_tokens", "statistic": "sum", "upper": 45,
            "window": {"requests": 2, "mode": "fixed"}}
    assert _statuses(goal) == [
        (1, 10.0, "met", 1), (2, 30.0, "met", 2), (3, 30.0, "met", 1),
        (4, 70.0, "violated", 2), (5, 50.0, "violated", 1),
    ]


def test_goal_sliding_window_is_the_last_n_requests_ending_with_each_request() -> None:
    goal = {"id": "sliding", "signal": "total_tokens", "statistic": "sum", "upper": 45,
            "window": {"requests": 2}}
    assert _statuses(goal) == [
        (1, 10.0, "met", 1), (2, 30.0, "met", 2), (3, 50.0, "violated", 2),
        (4, 70.0, "violated", 2), (5, 90.0, "violated", 2),
    ]


def test_goal_whole_run_window_and_lower_bound() -> None:
    goal = {"id": "floor", "signal": "total_tokens", "statistic": "mean", "lower": 25,
            "window": {"all": True, "mode": "sliding"}}
    assert _statuses(goal) == [
        (1, 10.0, "violated", 1), (2, 15.0, "violated", 2), (3, 20.0, "violated", 3),
        (4, 25.0, "met", 4), (5, 30.0, "met", 5),
    ]


def test_goal_uses_the_experiment_window_by_default() -> None:
    goal = {"id": "default", "signal": "total_tokens", "statistic": "sum", "upper": 45}
    assert [row[1] for row in _statuses(goal, default=WindowSpec(2, "fixed"))] == [10.0, 30.0, 30.0, 70.0, 50.0]


def test_goal_with_unavailable_reading_is_unknown_not_met() -> None:
    records = [_record(1, "A", {"total_tokens": 10}), _record(2, "A", {"total_tokens": None}),
               _record(3, "A", {"total_tokens": 5})]
    goal = {"id": "budget", "signal": "total_tokens", "statistic": "sum", "upper": 100,
            "window": {"requests": 2}}
    rows = evaluate_goals(records, [goal], candidates=["A"], signals=(), default_window=WindowSpec(2))
    assert [(row["status"], row["missingCount"]) for row in rows] == [("met", 0), ("unknown", 1), ("unknown", 1)]


def test_goal_ignores_requests_that_are_not_terminal() -> None:
    records = [*RECORDS[:2], {**RECORDS[2], "state": "started"}]
    goal = {"id": "sliding", "signal": "total_tokens", "statistic": "sum", "upper": 45, "window": {"requests": 2}}
    assert [row[0] for row in _statuses(goal, records)] == [1, 2]


def test_goal_table_is_reproducible_from_request_records_alone(tmp_path: Path) -> None:
    definition = _definition(request_count=4)
    definition["goals"] = [
        {"id": "fixed", "signal": "total_tokens", "statistic": "sum", "upper": 30,
         "window": {"requests": 2, "mode": "fixed"}},
        {"id": "latency", "signal": "latency_ms", "statistic": "max", "upper": 60000},
    ]
    run = plan(definition, output=tmp_path / "run")
    run.execute()
    tables = run.metric_tables()
    goal_rows = tables["goals"]
    assert len(goal_rows) == 8
    tokens = {row["requestId"]: row["total_tokens"] for row in tables["attempts"]}
    fixed = [row for row in goal_rows if row["goalId"] == "fixed"]
    # Hand-computed from the per-attempt token signal: blocks {1,2} and {3,4}.
    expected = [tokens["r-0001"], tokens["r-0001"] + tokens["r-0002"],
                tokens["r-0003"], tokens["r-0003"] + tokens["r-0004"]]
    assert [row["value"] for row in fixed] == expected
    assert [row["status"] for row in fixed] == ["met" if value <= 30 else "violated" for value in expected]

    # Only the plan and the request records are needed.
    copy = tmp_path / "records-only"
    copy.mkdir()
    for name in ("adaptive-plan.json", "manifest.json"):
        shutil.copy(run.root / name, copy / name)
    shutil.copytree(run.root / "adaptive-records", copy / "adaptive-records")
    assert build_adaptive_goal_metrics(copy) == goal_rows


# --- adaptive metric columns ----------------------------------------------------------------

def test_attempt_metrics_keep_usage_views_separate_and_accepted_boolean(tmp_path: Path) -> None:
    definition = _definition(request_count=2)
    run = plan(definition, output=tmp_path / "run")
    run.execute()
    run.metrics(output=tmp_path / "metrics")
    with (tmp_path / "metrics" / "adaptive_attempt_metrics.csv").open(encoding="utf-8") as handle:
        attempts = list(csv.DictReader(handle))
    with (tmp_path / "metrics" / "adaptive_request_metrics.csv").open(encoding="utf-8") as handle:
        request_fields = csv.DictReader(handle).fieldnames
    assert {row["accepted"] for row in attempts} == {"True"}
    assert {"total_tokens", "total_tokensProvenance", "latency_ms", "latency_msProvenance",
            "acceptedProvenance"} <= set(attempts[0])
    generation = {"generationTotalTokens", "generationDurationMs"}
    assessor = {"assessorTotalTokens", "assessorDurationMs", "knownAssessorTotalTokens"}
    evaluation = {"evaluationTotalTokens", "evaluationDurationMs"}
    assert generation | assessor | evaluation <= set(request_fields)
    assert {"labels.position", "policyId", "policyVersion", "failureCategory"} <= set(request_fields)
    assert not {"fallbackCount", "attemptsNotAccepted"} & set(request_fields)
    manifest = load_json(tmp_path / "metrics" / "metrics-manifest.json")
    assert "adaptive_goal_metrics.csv" in manifest["outputs"]


# --- summarize ------------------------------------------------------------------------------

def _plan_digest(root: Path) -> str:
    requests = load_json(root / "adaptive-plan.json")["requests"]
    return hashlib.sha256(json.dumps(requests, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def test_summarize_reports_workload_digest_and_separate_cost_views(tmp_path: Path) -> None:
    definition = _definition(request_count=3)
    definition["disturbances"] = [{"name": "fail-second", "version": "1", "component": "model",
                                   "kind": "failure", "firstSequence": 2, "lastSequence": 2,
                                   "seed": 0, "failureRate": 1.0}]
    definition["goals"] = [{"id": "tokens", "signal": "total_tokens", "statistic": "sum", "upper": 1,
                            "window": {"requests": 1}}]
    run = plan(definition, output=tmp_path / "run")
    run.execute()
    tables = run.metric_tables()
    attempt_tokens = [row["total_tokens"] for row in tables["attempts"]]
    delivered_tokens = [row["total_tokens"] for row in tables["attempts"] if row["delivered"]]
    assert len(delivered_tokens) == 2

    (row,) = summarize([run.root], signals=["total_tokens", "failed"])
    assert row["workloadDigest"] == _plan_digest(run.root)
    assert (row["requests"], row["delivered"], row["failed"], row["attempts"]) == (3, 2, 1, 3)
    assert row["failures.provider_error"] == 1
    available = [value for value in attempt_tokens if value is not None]
    assert row["signals.total_tokens.allAttempts.sampleCount"] == len(available)
    assert row["signals.total_tokens.allAttempts.missingCount"] == 3 - len(available)
    assert row["signals.total_tokens.deliveredRequests.sum"] == sum(delivered_tokens)
    assert row["signals.total_tokens.deliveredRequests.sampleCount"] == 2
    assert row["signals.failed.allAttempts.sum"] == 1
    assert row["signals.failed.deliveredRequests.sum"] == 0
    # The token signal of the mock provider is estimated; the sum must not hide that.
    assert row["signals.total_tokens.deliveredRequests.sumProvenance"] == "estimated"
    assert row["goals.tokens.violations"] == sum(
        goal["status"] == "violated" for goal in tables["goals"])


def test_summarize_counts_attempts_of_requests_that_never_became_terminal(tmp_path: Path, monkeypatch) -> None:
    import ctxbench.adaptive.workflow as workflow_module

    run = plan(_definition(request_count=1), output=tmp_path / "run")
    real_write = workflow_module.write_json

    def interrupt(path, value):
        if Path(path).parent.name == "adaptive-records" and value.get("state") == "delivered":
            raise RuntimeError("interrupted after durable execution")
        return real_write(path, value)

    monkeypatch.setattr(workflow_module, "write_json", interrupt)
    with pytest.raises(RuntimeError):
        run.execute()
    (row,) = summarize([str(run.root)], signals=["total_tokens"])
    assert (row["delivered"], row["failed"], row["attempts"]) == (0, 0, 1)
    assert row["signals.total_tokens.allAttempts.sampleCount"] == 1
    assert row["signals.total_tokens.deliveredRequests.sampleCount"] == 0


def test_summarize_digest_compares_workloads_not_policies(tmp_path: Path) -> None:
    first = plan(_definition(request_count=2), output=tmp_path / "a")
    other_policy = _definition(request_count=2)
    other_policy["policy"] = {"ref": "static", "params": {"candidate": "B"}}
    second = plan(other_policy, output=tmp_path / "b")
    third = plan(_definition(request_count=3), output=tmp_path / "c")
    rows = summarize([first, second.root, str(third.root)], signals=[])
    assert rows[0]["workloadDigest"] == rows[1]["workloadDigest"] != rows[2]["workloadDigest"]
    assert rows[0]["policyId"] == "static"


def test_analysis_accepts_paths_strings_and_run_handles(tmp_path: Path) -> None:
    run = plan(_definition(), output=tmp_path / "run")
    reopened = open_run(run.root)
    rows = summarize([run.root, str(run.root), reopened], signals=[])
    assert {row["runPath"] for row in rows} == {str(run.root.resolve())}
    with pytest.raises(TypeError):
        summarize([42], signals=[])


# --- headroom -------------------------------------------------------------------------------

def _benchmark_matrix(root: Path) -> Path:
    """Two candidates over three cells; candidate B failed on cell 3; A has two repeats on cell 1."""
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"workflowKind": "benchmark"}), encoding="utf-8")
    cells = [  # (instance, validation, candidate, tokens or None for a failed trial)
        ("i1", "judge", "cA", 8), ("i1", "judge", "cA", 12), ("i1", "judge", "cB", 20),
        ("i2", "judge", "cA", 30), ("i2", "judge", "cB", 15),
        ("i3", "exact", "cA", 5), ("i3", "exact", "cB", None),
    ]
    trials, responses = [], []
    for index, (instance, validation, configuration, tokens) in enumerate(cells):
        trial_id = f"t{index}"
        trials.append({"trialId": trial_id, "taskId": "task", "instanceId": instance, "modelId": "m",
                       "configurationId": configuration, "validationType": validation})
        responses.append({"trialId": trial_id, "status": "success" if tokens is not None else "error",
                          "metricsSummary": {"totalTokens": tokens}})
    for name, rows in (("trials.jsonl", trials), ("responses.jsonl", responses)):
        (root / name).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return root


A, B = '["m","cA"]', '["m","cB"]'


def test_headroom_reproduces_hand_computed_minimum(tmp_path: Path) -> None:
    report = headroom(_benchmark_matrix(tmp_path / "bench"), signal="total_tokens")
    # Complete cells: i1 (A mean 10, B 20) and i2 (A 30, B 15). Totals A=40, B=35.
    assert report.common_cells == 2
    assert (report.best_static_candidate, report.best_static) == (B, 35.0)
    assert report.oracle == 25.0
    assert report.oracle_gain_over_best_static == pytest.approx(10 / 35)
    assert report.candidate_oracle_win_share == {A: 0.5, B: 0.5}
    assert report.coverage[A] == {"totalCells": 3, "coveredCells": 3, "missingCells": 0}
    assert report.coverage[B] == {"totalCells": 3, "coveredCells": 2, "missingCells": 1}
    assert report.provenance == "derived" and "upper bound" in report.interpretation


def test_headroom_reproduces_hand_computed_maximum_and_groups(tmp_path: Path) -> None:
    root = _benchmark_matrix(tmp_path / "bench")
    report = headroom(root, signal="total_tokens", objective="max")
    assert (report.best_static_candidate, report.best_static, report.oracle) == (A, 40.0, 50.0)
    assert report.oracle_gain_over_best_static == pytest.approx(0.25)

    grouped = headroom(str(root), signal="total_tokens", by="validationType")
    groups = {row["group"]: row for row in grouped.groups}
    assert groups["judge"]["commonCells"] == 2 and groups["judge"]["oracle"] == 25.0
    assert groups["exact"]["commonCells"] == 0 and groups["exact"]["bestStatic"] is None
    assert (grouped.best_static, grouped.oracle) == (35.0, 25.0)


def test_headroom_refuses_adaptive_runs(tmp_path: Path) -> None:
    run = plan(_definition(), output=tmp_path / "run")
    with pytest.raises(ValueError, match="benchmark run"):
        headroom(run.root, signal="total_tokens")
