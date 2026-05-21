from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxbench.benchmark import evaluation as evaluation_module
from ctxbench.commands.eval import eval_command
from ctxbench.commands.execute import execute_command
from ctxbench.commands.export import export_command
from ctxbench.commands.plan import plan_command
from ctxbench.commands.status import status_command
from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset import acquisition as acquisition_module


def _forbid_dataset_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*args: object, **kwargs: object) -> object:
        raise AssertionError("dataset acquisition helper was called")

    for name in (
        "download_bytes",
        "resolve_archive_source",
        "require_checksum_for_remote_archive",
        "resolve_expected_sha256",
        "verify_downloaded_bytes",
    ):
        monkeypatch.setattr(acquisition_module, name, _blocked)


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
    (instance_dir / "blocks.json").write_text(
        json.dumps({"summary": "Researcher in software engineering."}),
        encoding="utf-8",
    )
    return root


def _write_experiment(path: Path, dataset_ref: object) -> Path:
    path.write_text(
        json.dumps(
            {
                "id": "exp-no-network",
                "output": "outputs",
                "dataset": dataset_ref,
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


def _write_missing_trials(root: Path) -> Path:
    trials_path = root / "trials.jsonl"
    trials_path.write_text(
        json.dumps(
            {
                "trialId": "trial-1",
                "experimentId": "exp-no-network",
                "taskId": "q_year",
                "question": "In which year did CV Demo obtain their PhD?",
                "questionTemplate": "In which year did {researcher_name} obtain their PhD?",
                "dataset": {
                    "id": "ctxbench/local-fixture",
                    "version": "0.1.0",
                    "origin": str(root / "missing-dataset"),
                    "resolvedRevision": None,
                    "contentHash": None,
                    "materializedPath": str(root / "missing-dataset"),
                },
                "instanceId": "cv-demo",
                "model": "mock",
                "modelId": "mock",
                "provider": "mock",
                "strategy": "inline",
                "format": "json",
                "params": {},
                "repeatIndex": 1,
                "outputRoot": str(root.resolve()),
                "evaluationEnabled": True,
                "trace": {"enabled": False, "writeFiles": False},
                "artifacts": {"writeJsonl": True, "writeIndividualJson": False},
                "questionTags": ["objective"],
                "validationType": "judge",
                "contextBlock": ["summary"],
                "parameters": {"researcher_name": "CV Demo"},
                "metadata": {
                    "canonicalId": "trial-1",
                    "taskId": "q_year",
                    "instanceId": "cv-demo",
                    "provider": "mock",
                    "modelId": "mock",
                    "modelName": "mock",
                    "strategy": "inline",
                    "format": "json",
                    "repeatIndex": 1,
                    "questionTags": ["objective"],
                    "validationType": "judge",
                    "parameters": {"researcher_name": "CV Demo"},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return trials_path


def _write_missing_responses(root: Path) -> Path:
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "experimentId": "exp-no-network",
                "dataset": {
                    "id": "ctxbench/local-fixture",
                    "version": "0.1.0",
                    "origin": str(root / "missing-dataset"),
                    "resolvedRevision": None,
                    "contentHash": None,
                    "materializedPath": str(root / "missing-dataset"),
                },
                "evaluation": {
                    "judges": [{"id": "judge-a", "provider": "mock", "model": "judge-a", "temperature": 0}]
                },
                "trace": {"writeFiles": False},
            }
        ),
        encoding="utf-8",
    )
    responses_path = root / "responses.jsonl"
    responses_path.write_text(
        json.dumps(
            {
                "trialId": "trial-1",
                "experimentId": "exp-no-network",
                "dataset": {
                    "id": "ctxbench/local-fixture",
                    "version": "0.1.0",
                    "origin": str(root / "missing-dataset"),
                    "resolvedRevision": None,
                    "contentHash": None,
                    "materializedPath": str(root / "missing-dataset"),
                },
                "taskId": "q_year",
                "question": "In which year did CV Demo obtain their PhD?",
                "questionTemplate": "In which year did {researcher_name} obtain their PhD?",
                "instanceId": "cv-demo",
                "provider": "mock",
                "modelId": "mock",
                "modelName": "mock",
                "strategy": "inline",
                "format": "json",
                "repeatIndex": 1,
                "outputRoot": str(root.resolve()),
                "status": "success",
                "response": "2020",
                "errorMessage": None,
                "timing": {
                    "startedAt": "2026-05-12T00:00:00Z",
                    "finishedAt": "2026-05-12T00:00:01Z",
                    "durationMs": 1,
                },
                "usage": {},
                "metricsSummary": {},
                "trace": {},
                "traceRef": None,
                "questionTags": ["objective"],
                "validationType": "judge",
                "contextBlock": ["summary"],
                "parameters": {"researcher_name": "CV Demo"},
                "metadata": {
                    "canonicalId": "trial-1",
                    "taskId": "q_year",
                    "instanceId": "cv-demo",
                    "provider": "mock",
                    "modelId": "mock",
                    "modelName": "mock",
                    "strategy": "inline",
                    "format": "json",
                    "repeatIndex": 1,
                    "questionTags": ["objective"],
                    "validationType": "judge",
                    "parameters": {"researcher_name": "CV Demo"},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return responses_path


def _write_export_fixture(root: Path) -> Path:
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "experimentId": "exp-no-network",
                "dataset": {
                    "id": "ctxbench/local-fixture",
                    "version": "0.1.0",
                    "origin": "forged-origin",
                    "resolvedRevision": None,
                    "contentHash": None,
                    "materializedPath": str(root / "missing-dataset"),
                },
                "evaluation": {"judges": []},
                "trace": {"writeFiles": False},
            }
        ),
        encoding="utf-8",
    )
    (root / "responses.jsonl").write_text(
        json.dumps(
            {
                "trialId": "trial-1",
                "experimentId": "exp-no-network",
                "dataset": {
                    "id": "ctxbench/local-fixture",
                    "version": "0.1.0",
                    "origin": "forged-origin",
                    "resolvedRevision": None,
                    "contentHash": None,
                    "materializedPath": str(root / "missing-dataset"),
                },
                "taskId": "q_year",
                "instanceId": "cv-demo",
                "provider": "mock",
                "modelId": "mock",
                "modelName": "mock",
                "strategy": "inline",
                "format": "json",
                "repeatIndex": 1,
                "status": "success",
                "response": "2020",
                "errorMessage": None,
                "timing": {
                    "startedAt": "2026-05-12T00:00:00Z",
                    "finishedAt": "2026-05-12T00:00:01Z",
                    "durationMs": 1,
                },
                "usage": {},
                "metricsSummary": {},
                "metadata": {
                    "canonicalId": "trial-1",
                    "taskId": "q_year",
                    "instanceId": "cv-demo",
                    "provider": "mock",
                    "modelId": "mock",
                    "modelName": "mock",
                    "strategy": "inline",
                    "format": "json",
                    "repeatIndex": 1,
                    "parameters": {},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "evals.jsonl").write_text(
        json.dumps(
            {
                "trialId": "trial-1",
                "experimentId": "exp-no-network",
                "dataset": {
                    "id": "ctxbench/local-fixture",
                    "version": "0.1.0",
                    "origin": "forged-origin",
                    "resolvedRevision": None,
                    "contentHash": None,
                    "materializedPath": str(root / "missing-dataset"),
                },
                "instanceId": "cv-demo",
                "taskId": "q_year",
                "strategy": "inline",
                "status": "evaluated",
                "evaluationMethod": "judge",
                "judgeCount": 1,
                "judgeErrorCount": 0,
                "outcome": {
                    "correctness": {"rating": "meets", "agreement": 1.0},
                    "completeness": {"rating": "meets", "agreement": 1.0},
                },
                "evaluationInputTokens": 1,
                "evaluationOutputTokens": 1,
                "evaluationTotalTokens": 2,
                "evaluationDurationMs": 1,
                "contextBlocks": ["summary"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "judge_votes.jsonl").write_text(
        json.dumps(
            {
                "trialId": "trial-1",
                "experimentId": "exp-no-network",
                "dataset": {
                    "id": "ctxbench/local-fixture",
                    "version": "0.1.0",
                    "origin": "forged-origin",
                    "resolvedRevision": None,
                    "contentHash": None,
                    "materializedPath": str(root / "missing-dataset"),
                },
                "instanceId": "cv-demo",
                "taskId": "q_year",
                "strategy": "inline",
                "judgeId": "judge-a",
                "provider": "mock",
                "model": "judge-a",
                "status": "evaluated",
                "criterias": {
                    "correctness": {"rating": "meets", "justification": "ok"},
                    "completeness": {"rating": "meets", "justification": "ok"},
                },
                "inputTokens": 1,
                "outputTokens": 1,
                "totalTokens": 2,
                "durationMs": 1,
                "error": None,
                "traceRef": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return root / "evals.jsonl"


def test_plan_rejects_unresolved_dataset_without_fetching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_dataset_fetch(monkeypatch)
    experiment_path = _write_experiment(
        tmp_path / "experiment.json",
        {"id": "ctxbench/missing", "version": "9.9.9"},
    )

    with pytest.raises(Exception) as excinfo:
        plan_command(str(experiment_path), output=str(tmp_path / "planned"), cache_dir=tmp_path / "cache")

    assert "ctxbench dataset fetch" in str(excinfo.value)


def test_execute_rejects_missing_planned_materialization_without_fetching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_dataset_fetch(monkeypatch)
    trials_path = _write_missing_trials(tmp_path)

    with pytest.raises(AdapterUnavailableError):
        execute_command(str(trials_path))


def test_eval_rejects_missing_dataset_evidence_without_fetching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_dataset_fetch(monkeypatch)
    responses_path = _write_missing_responses(tmp_path)

    original_judge_request = evaluation_module._judge_request
    evaluation_module._judge_request = lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("judge request should not run before dataset access")
    )
    try:
        with pytest.raises(FileNotFoundError):
            eval_command(str(responses_path))
    finally:
        evaluation_module._judge_request = original_judge_request


def test_export_succeeds_from_artifacts_alone_and_status_avoids_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _forbid_dataset_fetch(monkeypatch)
    evals_path = _write_export_fixture(tmp_path)

    def _resolver_used(*args: object, **kwargs: object) -> object:
        raise AssertionError("dataset resolver should not be used")

    monkeypatch.setattr("ctxbench.dataset.resolver.DatasetResolver.resolve", _resolver_used)

    assert export_command(str(evals_path)) == 0
    assert (tmp_path / "results.csv").exists()

    assert status_command(str(tmp_path)) == 0
    captured = capsys.readouterr()
    assert "exp-no-network" in captured.out
