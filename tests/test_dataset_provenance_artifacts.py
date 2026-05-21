from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ctxbench.benchmark import evaluation as evaluation_module
from ctxbench.benchmark.models import (
    DatasetProvenance,
    EvaluationJudgeInfo,
    EvaluationTrace,
    EvaluationResult,
    TrialResult,
    RunTiming,
    TrialTrace,
)
from ctxbench.commands.eval import eval_command
from ctxbench.commands.execute import execute_command
from ctxbench.commands.export import export_command
from ctxbench.commands.plan import plan_command
from ctxbench.util.jsonl import read_jsonl


def _write_local_dataset(root: Path) -> Path:
    instance_dir = root / "context" / "cv-demo"
    instance_dir.mkdir(parents=True, exist_ok=True)
    (root / "questions.json").write_text(
        json.dumps(
            {
                "datasetId": "ctxbench/local-fixture",
                "version": "0.1.0",
                "questions": [
                    {
                        "id": "q_year",
                        "question": "In which year did {researcher_name} obtain their PhD?",
                        "tags": ["objective"],
                        "validation": {"type": "judge"},
                        "contextBlock": ["summary"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "questions.instance.json").write_text(
        json.dumps(
            {
                "datasetId": "ctxbench/local-fixture",
                "version": "0.1.0",
                "instances": [
                    {
                        "instanceId": "cv-demo",
                        "questions": [{"id": "q_year", "parameters": {"researcher_name": "CV Demo"}}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (instance_dir / "parsed.json").write_text(json.dumps({"answers": {"q_year": 2020}}), encoding="utf-8")
    (instance_dir / "blocks.json").write_text(json.dumps({"summary": "Researcher in software engineering."}), encoding="utf-8")
    return root


def _write_experiment(path: Path, dataset_root: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "id": "exp-dataset-provenance",
                "output": "outputs",
                "dataset": {"root": str(dataset_root)},
                "scope": {"instances": [], "questions": []},
                "factors": {
                    "model": [{"provider": "mock", "name": "mock"}],
                    "strategy": ["inline"],
                    "format": ["json"],
                },
                "evaluation": {
                    "enabled": True,
                    "judges": [{"id": "judge-a", "provider": "mock", "model": "judge-a", "temperature": 0}],
                },
                "trace": {"writeFiles": False},
            }
        ),
        encoding="utf-8",
    )
    return path


def _fake_execute_runspec(runspec, engine) -> TrialResult:
    del engine
    return TrialResult(
        trialId=runspec.trialId,
        experimentId=runspec.experimentId,
        dataset=runspec.dataset,
        taskId=runspec.taskId,
        question=runspec.question,
        taskTemplate=runspec.taskTemplate,
        taskTags=list(runspec.taskTags),
        validationType=runspec.validationType,
        contextBlocks=list(runspec.contextBlocks),
        parameters=dict(runspec.parameters),
        instanceId=runspec.instanceId,
        provider=runspec.provider,
        modelId=runspec.modelId,
        modelName=runspec.modelName,
        strategy=runspec.strategy,
        format=runspec.format,
        repeatIndex=runspec.repeatIndex,
        outputRoot=runspec.outputRoot,
        response="2020",
        status="success",
        errorMessage=None,
        timing=RunTiming(
            startedAt="2026-05-12T00:00:00Z",
            finishedAt="2026-05-12T00:00:01Z",
            durationMs=1,
        ),
        usage={},
        metricsSummary={},
        trace=TrialTrace(),
        traceRef=None,
        evaluation=EvaluationResult(),
        metadata=runspec.metadata,
    )


def _fake_judge_request(**kwargs):
    config = kwargs["config"]
    return (
        {
            "correctness": {"rating": "meets", "justification": config.model},
            "completeness": {"rating": "meets", "justification": config.model},
        },
        EvaluationJudgeInfo(
            used=True,
            role="judge",
            provider=config.provider,
            model=config.model,
            inputTokens=1,
            outputTokens=1,
            durationMs=1,
        ),
        EvaluationTrace(),
    )


def test_dataset_provenance_is_preserved_across_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")
    experiment_path = _write_experiment(tmp_path / "experiment.json", dataset_root)
    output_root = tmp_path / "planned"

    assert plan_command(str(experiment_path), output=str(output_root), cache_dir=tmp_path / "cache") == 0

    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    planned_dataset = manifest["dataset"]
    assert planned_dataset["id"] == "ctxbench/local-fixture"
    assert planned_dataset["version"] == "0.1.0"

    monkeypatch.setattr("ctxbench.commands.execute.execute_runspec", _fake_execute_runspec)
    assert execute_command(str(output_root / "trials.jsonl")) == 0

    original_judge_request = evaluation_module._judge_request
    evaluation_module._judge_request = _fake_judge_request
    try:
        assert eval_command(str(output_root / "responses.jsonl")) == 0
    finally:
        evaluation_module._judge_request = original_judge_request

    assert export_command(str(output_root / "evals.jsonl")) == 0

    trials = read_jsonl(output_root / "trials.jsonl")
    responses = read_jsonl(output_root / "responses.jsonl")
    evals = read_jsonl(output_root / "evals.jsonl")
    votes = read_jsonl(output_root / "judge_votes.jsonl")
    rows = list(csv.DictReader((output_root / "results.csv").read_text(encoding="utf-8").splitlines()))

    expected = planned_dataset
    for artifact_rows in (trials, responses, evals, votes):
        assert artifact_rows
        assert artifact_rows[0]["dataset"]["id"] == expected["id"]
        assert artifact_rows[0]["dataset"]["version"] == expected["version"]
        assert artifact_rows[0]["dataset"] == expected

    assert rows
    assert rows[0]["dataset_id"] == expected["id"]
    assert rows[0]["dataset_version"] == expected["version"]


def test_execute_and_eval_do_not_recompute_dataset_provenance_from_another_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")
    experiment_path = _write_experiment(tmp_path / "experiment.json", dataset_root)
    output_root = tmp_path / "planned"

    assert plan_command(str(experiment_path), output=str(output_root), cache_dir=tmp_path / "cache") == 0
    trials = read_jsonl(output_root / "trials.jsonl")
    forged = DatasetProvenance.model_validate(trials[0]["dataset"]).model_dump(mode="json")
    forged["id"] = "ctxbench/forged"
    forged["version"] = "9.9.9"
    forged["origin"] = "forged-origin"
    (output_root / "trials.jsonl").write_text(
        "".join(
            json.dumps({**row, "dataset": forged}, sort_keys=True) + "\n"
            for row in trials
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("ctxbench.commands.execute.execute_runspec", _fake_execute_runspec)
    assert execute_command(str(output_root / "trials.jsonl")) == 0

    original_judge_request = evaluation_module._judge_request
    evaluation_module._judge_request = _fake_judge_request
    try:
        assert eval_command(str(output_root / "responses.jsonl")) == 0
    finally:
        evaluation_module._judge_request = original_judge_request

    responses = read_jsonl(output_root / "responses.jsonl")
    evals = read_jsonl(output_root / "evals.jsonl")
    votes = read_jsonl(output_root / "judge_votes.jsonl")

    assert responses[0]["dataset"] == forged
    assert evals[0]["dataset"] == forged
    assert votes[0]["dataset"] == forged
