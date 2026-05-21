from __future__ import annotations

import json
import csv
from pathlib import Path

from ctxbench.benchmark import evaluation as evaluation_module
from ctxbench.commands.eval import eval_command
from ctxbench.commands.export import export_command
from ctxbench.commands.status import status_command


def _write_eval_fixture(root: Path) -> Path:
    dataset_root = root / "dataset"
    instance_dir = dataset_root / "context" / "cv_demo"
    instance_dir.mkdir(parents=True, exist_ok=True)

    (dataset_root / "questions.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v1",
                "questions": [
                    {
                        "id": "q_one",
                        "question": "Question one?",
                        "validation": {"type": "judge"},
                        "contextBlock": ["q_one"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (dataset_root / "questions.instance.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v1",
                "instances": [
                    {
                        "instanceId": "cv_demo",
                        "contextBlocks": "context/cv_demo/blocks.json",
                        "questions": [{"id": "q_one"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (instance_dir / "blocks.json").write_text(
        json.dumps(
            {
                "blocks": {
                    "q_one": {
                        "title": "q_one",
                        "summary": "Some context for the question.",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    (root / "manifest.json").write_text(
        json.dumps(
            {
                "experimentId": "exp_mock",
                "trialId": "run-1",
                "taskId": "q_one",
                "evaluation": {
                    "judges": [
                        {"id": "judge-a", "provider": "mock", "model": "judge-a", "temperature": 0},
                        {"id": "judge-b", "provider": "mock", "model": "judge-b", "temperature": 0},
                    ]
                },
                "trace": {"writeFiles": False},
            }
        ),
        encoding="utf-8",
    )

    (root / "trials.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "trialId": "run-1",
                        "experimentId": "exp_mock",
                        "instanceId": "cv_demo",
                        "taskId": "q_one",
                        "provider": "mock",
                        "modelId": "model",
                        "modelName": "model",
                        "strategy": "inline",
                        "format": "json",
                        "repeatIndex": 1,
                        "metadata": {
                            "canonicalId": "run-1",
                            "taskId": "q_one",
                            "instanceId": "cv_demo",
                            "provider": "mock",
                            "modelId": "model",
                            "modelName": "model",
                            "strategy": "inline",
                            "format": "json",
                            "repeatIndex": 1,
                            "validationType": "judge",
                            "parameters": {},
                        },
                    }
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (root / "responses.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "trialId": "run-1",
                        "experimentId": "exp_mock",
                        "dataset": {"root": str(dataset_root.resolve())},
                        "taskId": "q_one",
                        "question": "Question one?",
                        "taskTemplate": None,
                        "instanceId": "cv_demo",
                        "provider": "mock",
                        "modelId": "model",
                        "modelName": "model",
                        "strategy": "inline",
                        "format": "json",
                        "repeatIndex": 1,
                        "validationType": "judge",
                        "outputRoot": str(root.resolve()),
                        "status": "success",
                        "response": "Answer",
                        "errorMessage": None,
                        "timing": {
                            "startedAt": "2026-05-02T00:00:00Z",
                            "finishedAt": "2026-05-02T00:00:01Z",
                            "durationMs": 1,
                        },
                        "usage": {},
                        "metricsSummary": {},
                        "trace": {},
                        "traceRef": None,
                        "evaluation": {},
                        "metadata": {
                            "canonicalId": "run-1",
                            "taskId": "q_one",
                            "instanceId": "cv_demo",
                            "provider": "mock",
                            "modelId": "model",
                            "modelName": "model",
                            "strategy": "inline",
                            "format": "json",
                            "repeatIndex": 1,
                            "validationType": "judge",
                            "parameters": {},
                        },
                    }
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def test_eval_force_with_judge_preserves_other_judges(tmp_path):
    root = _write_eval_fixture(tmp_path)
    state = {"version": 0}

    def fake_judge_request(**kwargs):
        state["version"] += 1
        config = kwargs["config"]
        just = f"{config.model}-v{state['version']}"
        return (
            {
                "correctness": {"rating": "meets", "justification": just},
                "completeness": {"rating": "meets", "justification": just},
            },
            evaluation_module.EvaluationJudgeInfo(
                used=True,
                role="judge",
                provider=config.provider,
                model=config.model,
            ),
            evaluation_module.EvaluationTrace(),
        )

    original = evaluation_module._judge_request
    evaluation_module._judge_request = fake_judge_request
    try:
        assert eval_command(str(root / "responses.jsonl")) == 0

        eval_rows = [json.loads(line) for line in (root / "evals.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(eval_rows) == 1
        assert eval_rows[0]["judgeCount"] == 2
        assert eval_rows[0]["trialId"] == "run-1"
        assert eval_rows[0]["taskId"] == "q_one"
        assert {"trialId", "taskId", "judgeCount"} <= set(eval_rows[0])
        summary = json.loads((root / "evals-summary.json").read_text(encoding="utf-8"))
        assert summary["tasks"][0]["trialId"] == "run-1"
        assert summary["tasks"][0]["taskId"] == "q_one"
        assert {"trialId", "taskId"} <= set(summary["tasks"][0])

        judge_votes = [json.loads(line) for line in (root / "judge_votes.jsonl").read_text(encoding="utf-8").splitlines()]
        votes_by_id = {row["judgeId"]: row for row in judge_votes}
        assert set(votes_by_id) == {"judge-a", "judge-b"}
        assert all(row["trialId"] == "run-1" for row in judge_votes)
        assert all(row["taskId"] == "q_one" for row in judge_votes)
        assert all({"trialId", "taskId", "judgeId"} <= set(row) for row in judge_votes)
        assert votes_by_id["judge-a"]["criterias"]["correctness"]["justification"] == "judge-a-v1"
        assert votes_by_id["judge-b"]["criterias"]["correctness"]["justification"] == "judge-b-v2"
        assert all(row["status"] == "evaluated" for row in judge_votes)

        state["version"] = 9
        assert eval_command(
            str(root / "responses.jsonl"),
            force=True,
            judge=("judge-a",),
        ) == 0

        eval_rows = [json.loads(line) for line in (root / "evals.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(eval_rows) == 1
        assert eval_rows[0]["judgeCount"] == 2

        judge_votes = [json.loads(line) for line in (root / "judge_votes.jsonl").read_text(encoding="utf-8").splitlines()]
        judges_by_id = {row["judgeId"]: row for row in judge_votes}
        assert judges_by_id["judge-a"]["criterias"]["correctness"]["justification"] == "judge-a-v10"
        assert judges_by_id["judge-b"]["criterias"]["correctness"]["justification"] == "judge-b-v2"
    finally:
        evaluation_module._judge_request = original


def test_status_breaks_down_by_judge(tmp_path, capsys):
    root = _write_eval_fixture(tmp_path)

    def fake_judge_request(**kwargs):
        config = kwargs["config"]
        just = f"{config.model}-ok"
        return (
            {
                "correctness": {"rating": "meets", "justification": just},
                "completeness": {"rating": "meets", "justification": just},
            },
            evaluation_module.EvaluationJudgeInfo(
                used=True,
                role="judge",
                provider=config.provider,
                model=config.model,
            ),
            evaluation_module.EvaluationTrace(),
        )

    original = evaluation_module._judge_request
    evaluation_module._judge_request = fake_judge_request
    try:
        assert eval_command(str(root / "responses.jsonl")) == 0
        assert status_command(str(root), by="judge") == 0
        out = capsys.readouterr().out
        assert "Judge" in out
        assert "judge-a" in out
        assert "judge-b" in out
        assert "Success" in out
        assert "Pending" in out
        assert "execute" in out
    finally:
        evaluation_module._judge_request = original


def test_export_reads_responses_and_emits_target_fields(tmp_path):
    root = _write_eval_fixture(tmp_path)

    (root / "evals.jsonl").write_text(
        json.dumps(
            {
                "trialId": "run-1",
                "experimentId": "exp_mock",
                "instanceId": "cv_demo",
                "taskId": "q_one",
                "strategy": "inline",
                "status": "evaluated",
                "evaluationMethod": "judge",
                "judgeCount": 1,
                "judgeErrorCount": 0,
                "outcome": {
                    "correctness": {"rating": "meets", "agreement": True},
                    "completeness": {"rating": "meets", "agreement": True},
                },
                "evaluationInputTokens": 3,
                "evaluationOutputTokens": 2,
                "evaluationTotalTokens": 5,
                "evaluationDurationMs": 4,
                "contextBlocks": ["q_one"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "judge_votes.jsonl").write_text(
        json.dumps(
            {
                "trialId": "run-1",
                "experimentId": "exp_mock",
                "instanceId": "cv_demo",
                "taskId": "q_one",
                "strategy": "inline",
                "judgeId": "judge-a",
                "provider": "mock",
                "model": "judge-a",
                "status": "evaluated",
                "criterias": {
                    "correctness": {"rating": "meets", "justification": "ok"},
                    "completeness": {"rating": "meets", "justification": "ok"},
                },
                "inputTokens": 3,
                "outputTokens": 2,
                "totalTokens": 5,
                "durationMs": 4,
                "error": None,
                "traceRef": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert export_command(str(root / "evals.jsonl")) == 0

    with (root / "results.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    row = rows[0]
    assert row["trialId"] == "run-1"
    assert row["taskId"] == "q_one"
    assert row["response"] == "Answer"
    assert {"trialId", "taskId", "response"} <= set(row)


def test_status_counts_trials_and_responses(tmp_path, capsys):
    root = _write_eval_fixture(tmp_path)

    (root / "evals.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "trialId": "run-1",
                        "experimentId": "exp_mock",
                        "instanceId": "cv_demo",
                        "taskId": "q_one",
                        "status": "evaluated",
                        "evaluationMethod": "judge",
                        "judgeCount": 1,
                        "judgeErrorCount": 0,
                        "outcome": None,
                    }
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert status_command(str(root)) == 0
    out = capsys.readouterr().out
    assert "execute" in out
    assert "eval" in out
    assert " 1" in out
