from __future__ import annotations

import csv
import json
from pathlib import Path

from ctxbench.benchmark import evaluation as evaluation_module
from ctxbench.benchmark.models import Experiment
from ctxbench.benchmark.paths import (
    resolve_evals_path,
    resolve_output_root,
    resolve_responses_path,
    resolve_trials_path,
)
from ctxbench.commands.eval import eval_command
from ctxbench.commands.export import export_command
from ctxbench.commands.plan import plan_command
from ctxbench.commands.status import status_command


def _write_plan_fixture(root: Path) -> Path:
    dataset_root = root / "dataset"
    context_dir = dataset_root / "context" / "cv_demo"
    context_dir.mkdir(parents=True, exist_ok=True)

    (dataset_root / "tasks.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v1",
                "tasks": [
                    {
                        "id": "q_one",
                        "question": "Question one?",
                        "validation": {"type": "judge"},
                        "contextBlocks": ["q_one"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (dataset_root / "tasks.instance.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v1",
                "instances": [
                    {
                        "instanceId": "cv_demo",
                        "contextBlocks": "context/cv_demo/blocks.json",
                        "tasks": [{"id": "q_one"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (context_dir / "blocks.json").write_text(
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

    experiment_path = root / "experiment.json"
    experiment_path.write_text(
        json.dumps(
            {
                "id": "exp_artifacts",
                "dataset": str(dataset_root.resolve()),
                "scope": {"instances": ["cv_demo"], "tasks": ["q_one"]},
                "factors": {
                    "model": [{"provider": "mock", "name": "mock-model"}],
                    "strategy": ["inline"],
                    "format": ["json"],
                },
                "execution": {"repeats": 1},
                "trace": {"writeFiles": False},
            }
        ),
        encoding="utf-8",
    )
    return experiment_path


def _write_eval_fixture(root: Path) -> Path:
    dataset_root = root / "dataset"
    instance_dir = dataset_root / "context" / "cv_demo"
    instance_dir.mkdir(parents=True, exist_ok=True)

    (dataset_root / "tasks.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v1",
                "tasks": [
                    {
                        "id": "q_one",
                        "question": "Question one?",
                        "validation": {"type": "judge"},
                        "contextBlocks": ["q_one"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (dataset_root / "tasks.instance.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v1",
                "instances": [
                    {
                        "instanceId": "cv_demo",
                        "contextBlocks": "context/cv_demo/blocks.json",
                        "tasks": [{"id": "q_one"}],
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
                        {"id": "judge-a", "provider": "mock", "model": "judge-a", "temperature": 0}
                    ]
                },
                "trace": {"writeFiles": False},
            }
        ),
        encoding="utf-8",
    )

    (root / "trials.jsonl").write_text(
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
                "dataset": {"root": str(dataset_root.resolve())},
                "taskStatement": "Question one?",
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
        + "\n",
        encoding="utf-8",
    )

    (root / "responses.jsonl").write_text(
        json.dumps(
            {
                "trialId": "run-1",
                "experimentId": "exp_mock",
                "dataset": {"root": str(dataset_root.resolve())},
                "taskId": "q_one",
                "taskStatement": "Question one?",
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
        + "\n",
        encoding="utf-8",
    )
    return root


def test_artifact_path_resolution_uses_target_names() -> None:
    experiment = Experiment.model_validate(
        {
            "id": "exp_artifacts",
            "dataset": "/tmp/dataset",
            "factors": {
                "model": [{"provider": "mock", "name": "mock-model"}],
                "strategy": ["inline"],
                "format": ["json"],
            },
        }
    )
    base_dir = Path("/tmp/base")

    output_root = resolve_output_root(experiment, base_dir)
    assert resolve_trials_path(experiment, base_dir) == output_root / "trials.jsonl"
    assert resolve_responses_path(experiment, base_dir) == output_root / "responses.jsonl"
    assert resolve_evals_path(experiment, base_dir) == output_root / "evals.jsonl"


def test_plan_command_writes_target_artifacts_only(tmp_path: Path) -> None:
    experiment_path = _write_plan_fixture(tmp_path)

    assert plan_command(str(experiment_path)) == 0

    output_root = tmp_path / "outputs" / "exp_artifacts"
    assert (output_root / "manifest.json").exists()
    assert (output_root / "trials.jsonl").exists()
    assert not (output_root / "queries.jsonl").exists()
    assert not (output_root / "answers.jsonl").exists()


def test_eval_ignores_legacy_answers_when_target_responses_present(tmp_path: Path) -> None:
    root = _write_eval_fixture(tmp_path)
    (root / "answers.jsonl").write_text("{bad json\n", encoding="utf-8")

    def fake_judge_request(**kwargs):
        config = kwargs["config"]
        return (
            {
                "correctness": {"rating": "meets", "justification": config.model},
                "completeness": {"rating": "meets", "justification": config.model},
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
    finally:
        evaluation_module._judge_request = original

    assert (root / "evals.jsonl").exists()
    eval_rows = [json.loads(line) for line in (root / "evals.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["trialId"] for row in eval_rows] == ["run-1"]


def test_export_and_status_ignore_legacy_files_when_target_files_exist(
    tmp_path: Path,
    capsys,
) -> None:
    root = _write_eval_fixture(tmp_path)

    (root / "queries.jsonl").write_text(
        json.dumps({"trialId": "legacy-run", "status": "success"}) + "\n",
        encoding="utf-8",
    )
    (root / "answers.jsonl").write_text(
        json.dumps(
            {
                "trialId": "legacy-run",
                "experimentId": "legacy-exp",
                "instanceId": "legacy-instance",
                "taskId": "legacy-task",
                "response": "Legacy answer",
                "status": "success",
                "timing": {},
                "dataset": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
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

    assert status_command(str(root)) == 0
    status_output = capsys.readouterr().out
    assert "Experiment : exp_mock" in status_output
    assert "legacy-run" not in status_output

    assert export_command(str(root / "evals.jsonl")) == 0
    with (root / "results.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert rows[0]["trialId"] == "run-1"
    assert rows[0]["response"] == "Answer"
