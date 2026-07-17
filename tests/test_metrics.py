from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from ctxbench.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_metrics_planned_only_writes_canonical_tree(tmp_path):
    root = _experiment(tmp_path / "exp", responses=[], evals=[])

    assert main(["metrics", str(root)]) == 0

    metrics = root / "metrics"
    expected = {
        "metrics-manifest.json",
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
    }
    assert {str(path.relative_to(metrics)) for path in metrics.rglob("*") if path.is_file()} == expected
    rows = _csv_rows(metrics / "trial_metrics.csv")
    assert len(rows) == 1
    assert rows[0]["response_present"] == "false"
    assert rows[0]["evaluation_present"] == "false"
    assert rows[0]["configuration"] == "inline_json"
    assert _csv_rows(metrics / "failure_cases.csv") == []


def test_metrics_force_required_for_non_empty_output(tmp_path):
    root = _experiment(tmp_path / "exp")
    metrics = root / "metrics"
    metrics.mkdir()
    (metrics / "old.txt").write_text("old", encoding="utf-8")

    assert main(["metrics", str(root)]) == 1
    assert (metrics / "old.txt").exists()

    assert main(["metrics", str(root), "--force"]) == 0
    assert not (metrics / "old.txt").exists()
    assert (metrics / "trial_metrics.csv").exists()


def test_metrics_missing_trials_single_fails_multi_warns_and_skips(tmp_path):
    missing = tmp_path / "missing"
    missing.mkdir()
    valid = _experiment(tmp_path / "valid")

    assert main(["metrics", str(missing)]) == 1
    out = tmp_path / "merged_metrics"
    assert main(["metrics", str(missing), str(valid), "--output", str(out)]) == 0
    assert len(_csv_rows(out / "trial_metrics.csv")) == 1


def test_metrics_multi_input_requires_output_and_duplicate_trial_ids_fail(tmp_path):
    first = _experiment(tmp_path / "first")
    second = _experiment(tmp_path / "second")

    assert main(["metrics", str(first), str(second)]) == 1
    assert main(["metrics", str(first), str(second), "--output", str(tmp_path / "merged")]) == 1


def test_metrics_primary_effectiveness_and_failure_cases(tmp_path):
    response = _response("t1", status="success", metrics={"totalTokens": 10, "totalDurationMs": 2000, "modelCalls": 1})
    evaluation = _judge_eval("t1", correctness="meets", completeness="partial", c_agreement=1, k_agreement=0)
    votes = [
        _vote("t1", "a", correctness="meets", completeness="partial"),
        _vote("t1", "b", correctness="meets", completeness="misses"),
    ]
    root = _experiment(tmp_path / "exp", responses=[response], evals=[evaluation], votes=votes)

    assert main(["metrics", str(root)]) == 0

    row = _csv_rows(root / "metrics" / "trial_metrics.csv")[0]
    assert row["primary_metric_name"] == "judge_meets"
    assert row["primary_success"] == "false"
    assert row["primary_score"] == "0.75"
    assert row["judge_agreement_mean"] == "0.5"
    assert row["judge_unanimous"] == "false"
    failure = _csv_rows(root / "metrics" / "failure_cases.csv")[0]
    assert failure["trialId"] == "t1"


def test_metrics_repoqa_primary_uses_persisted_eval_only(tmp_path):
    trial = _trial("repoqa-1", validation_type="repoqa-scorer")
    evaluation = {
        "trialId": "repoqa-1",
        "status": "evaluated",
        "evaluationMethod": "repoqa-scorer",
        "details": {"outcome": {"passed": True}, "repoqa": {"bestSimilarScore": 0.875}},
    }
    root = _experiment(tmp_path / "exp", trials=[trial], responses=[_response("repoqa-1")], evals=[evaluation])

    assert main(["metrics", str(root)]) == 0

    row = _csv_rows(root / "metrics" / "trial_metrics.csv")[0]
    assert row["primary_metric_name"] == "pass"
    assert row["primary_success"] == "true"
    assert row["primary_score"] == "0.875"


def test_metrics_selectors_and_custom_group_by(tmp_path):
    trials = [
        _trial("t1", task_id="q1", model_id="m1"),
        _trial("t2", task_id="q2", model_id="m2"),
    ]
    responses = [_response("t1", status="success"), _response("t2", status="error")]
    root = _experiment(tmp_path / "exp", trials=trials, responses=responses, evals=[])

    assert main(["metrics", str(root), "--status", "success", "--group-by", "dataset_id,modelId"]) == 0

    rows = _csv_rows(root / "metrics" / "trial_metrics.csv")
    assert [row["trialId"] for row in rows] == ["t1"]
    aggregate = _csv_rows(root / "metrics" / "aggregate_metrics.csv")
    assert aggregate[0]["modelId"] == "m1"


def test_metrics_rejects_pipe_in_task_tags(tmp_path):
    root = _experiment(tmp_path / "exp", trials=[_trial("t1", tags=["bad|tag"])])

    assert main(["metrics", str(root)]) == 1


def test_metrics_observability_from_trace_and_usage(tmp_path):
    root = _experiment(
        tmp_path / "exp",
        responses=[
            _response(
                "t1",
                metrics={"inputTokens": 3, "toolCalls": 0, "mcpToolCalls": 1, "totalDurationMs": 1000},
                trace_ref="traces/executions/t1.json",
                strategy="local_mcp",
            )
        ],
    )
    trace_path = root / "traces" / "executions"
    trace_path.mkdir(parents=True)
    (trace_path / "t1.json").write_text(
        json.dumps({"nativeMcp": {"enabled": True}, "serverMcp": [{"name": "server"}]}),
        encoding="utf-8",
    )

    assert main(["metrics", str(root)]) == 0

    row = _csv_rows(root / "metrics" / "trial_metrics.csv")[0]
    assert row["execution_trace_available"] == "true"
    assert row["usage_observable"] == "true"
    assert row["native_mcp_observable"] == "true"
    assert row["server_mcp_observable"] == "true"


def test_metrics_accepts_artifact_only_unavailable_dataset_fixture(tmp_path):
    source = REPO_ROOT / "tests" / "fixtures" / "artifact_only_unavailable_dataset"
    root = tmp_path / "artifact_only"
    shutil.copytree(source, root)

    assert main(["metrics", str(root)]) == 0

    row = _csv_rows(root / "metrics" / "trial_metrics.csv")[0]
    assert row["dataset_id"] == "ctxbench/lattes"
    assert row["primary_success"] == "true"


def test_metrics_deterministic_csv_outputs(tmp_path):
    root = _experiment(tmp_path / "exp")

    assert main(["metrics", str(root)]) == 0
    first = {
        path.relative_to(root / "metrics"): path.read_text(encoding="utf-8")
        for path in (root / "metrics").rglob("*.csv")
    }
    assert main(["metrics", str(root), "--force"]) == 0
    second = {
        path.relative_to(root / "metrics"): path.read_text(encoding="utf-8")
        for path in (root / "metrics").rglob("*.csv")
    }
    assert first == second
    assert not (root / "metrics" / "plot_data").exists()


def _experiment(
    root: Path,
    *,
    trials: list[dict[str, object]] | None = None,
    responses: list[dict[str, object]] | None = None,
    evals: list[dict[str, object]] | None = None,
    votes: list[dict[str, object]] | None = None,
) -> Path:
    root.mkdir(parents=True)
    trial_rows = trials or [_trial("t1")]
    _write_jsonl(root / "trials.jsonl", trial_rows)
    if responses is None:
        responses = [_response(str(trial_rows[0]["trialId"]))]
    if responses:
        _write_jsonl(root / "responses.jsonl", responses)
    if evals is None:
        evals = [_judge_eval(str(trial_rows[0]["trialId"]))]
    if evals:
        _write_jsonl(root / "evals.jsonl", evals)
    if votes:
        _write_jsonl(root / "judge_votes.jsonl", votes)
    (root / "manifest.json").write_text(
        json.dumps({"experimentId": "exp", "dataset": {"contentHash": "sha256:test"}}),
        encoding="utf-8",
    )
    return root


def _trial(
    trial_id: str,
    *,
    task_id: str = "q1",
    model_id: str = "m1",
    validation_type: str = "judge",
    tags: list[str] | None = None,
) -> dict[str, object]:
    return {
        "trialId": trial_id,
        "experimentId": "exp",
        "dataset": {"id": "dataset", "version": "v1"},
        "instanceId": "i1",
        "taskId": task_id,
        "taskTags": tags if tags is not None else ["tag"],
        "provider": "mock",
        "modelId": model_id,
        "modelName": model_id,
        "strategy": "inline",
        "format": "json",
        "repeatIndex": 1,
        "validationType": validation_type,
    }


def _response(
    trial_id: str,
    *,
    status: str = "success",
    metrics: dict[str, object] | None = None,
    trace_ref: str | None = None,
    strategy: str = "inline",
) -> dict[str, object]:
    return {
        "trialId": trial_id,
        "status": status,
        "response": "answer",
        "errorMessage": None if status == "success" else "failed",
        "metricsSummary": metrics if metrics is not None else {"totalTokens": 5, "totalDurationMs": 1000},
        "usage": {"reasoningTokens": 1},
        "traceRef": trace_ref,
        "strategy": strategy,
    }


def _judge_eval(
    trial_id: str,
    *,
    correctness: str = "meets",
    completeness: str = "meets",
    c_agreement: object = True,
    k_agreement: object = True,
) -> dict[str, object]:
    return {
        "trialId": trial_id,
        "status": "evaluated",
        "evaluationMethod": "judge",
        "judgeCount": 2,
        "judgeErrorCount": 0,
        "outcome": {
            "correctness": {"rating": correctness, "agreement": c_agreement},
            "completeness": {"rating": completeness, "agreement": k_agreement},
        },
        "evaluationInputTokens": 2,
        "evaluationOutputTokens": 1,
        "evaluationDurationMs": 500,
    }


def _vote(trial_id: str, judge_id: str, *, correctness: str, completeness: str) -> dict[str, object]:
    return {
        "trialId": trial_id,
        "judgeId": judge_id,
        "status": "evaluated",
        "criterias": {
            "correctness": {"rating": correctness},
            "completeness": {"rating": completeness},
        },
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))

