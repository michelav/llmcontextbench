from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ctxbench.benchmark import evaluation as evaluation_module
from ctxbench.benchmark.checkpoints import load_completed_run_ids, write_completed_run_ids
from ctxbench.commands.eval import eval_command
from ctxbench.commands.execute import execute_command
from ctxbench.commands.export import export_command
from ctxbench.commands.plan import plan_command
from ctxbench.commands.status import status_command
from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset import acquisition as acquisition_module


ARTIFACT_ONLY_FIXTURE = Path(__file__).parent / "fixtures" / "artifact_only_unavailable_dataset"


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
    (root / "tasks.json").write_text(
        json.dumps(
            {
                "datasetId": "ctxbench/local-fixture",
                "version": "0.1.0",
                "tasks": [
                    {
                        "id": "q_year",
                        "statement": "In which year did {researcher_name} obtain their PhD?",
                        "tags": ["objective"],
                        "validation": {"type": "judge"},
                        "contextBlocks": ["summary"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "tasks.instance.json").write_text(
        json.dumps(
            {
                "datasetId": "ctxbench/local-fixture",
                "version": "0.1.0",
                "instances": [
                    {
                        "instanceId": "cv-demo",
                        "tasks": [{"id": "q_year", "parameters": {"researcher_name": "CV Demo"}}],
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
                "scope": {"instances": [], "tasks": []},
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


def test_trial_checkpoint_kind_accepts_canonical_and_legacy(tmp_path: Path) -> None:
    checkpoint = tmp_path / "runs.checkpoint.json"

    write_completed_run_ids(
        checkpoint,
        experiment_id="exp-1",
        kind="trials",
        completed_run_ids={"trial-1"},
    )

    assert load_completed_run_ids(checkpoint, experiment_id="exp-1", kind="trials") == {"trial-1"}

    checkpoint.write_text(
        json.dumps(
            {
                "experimentId": "exp-1",
                "kind": "runs",
                "completedTrialIds": ["legacy-trial"],
            }
        ),
        encoding="utf-8",
    )

    assert load_completed_run_ids(checkpoint, experiment_id="exp-1", kind="trials") == {"legacy-trial"}


def _write_missing_trials(root: Path) -> Path:
    trials_path = root / "trials.jsonl"
    trials_path.write_text(
        json.dumps(
            {
                "trialId": "trial-1",
                "experimentId": "exp-no-network",
                "taskId": "q_year",
                "taskStatement": "In which year did CV Demo obtain their PhD?",
                "taskTemplate": "In which year did {researcher_name} obtain their PhD?",
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
                "taskTags": ["objective"],
                "validationType": "judge",
                "contextBlocks": ["summary"],
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
                    "taskTags": ["objective"],
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
                "taskStatement": "In which year did CV Demo obtain their PhD?",
                "taskTemplate": "In which year did {researcher_name} obtain their PhD?",
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
                "taskTags": ["objective"],
                "validationType": "judge",
                "contextBlocks": ["summary"],
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
                    "taskTags": ["objective"],
                    "validationType": "judge",
                    "parameters": {"researcher_name": "CV Demo"},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return responses_path


def _copy_artifact_only_fixture(root: Path) -> Path:
    shutil.copytree(ARTIFACT_ONLY_FIXTURE, root, dirs_exist_ok=True)
    return root / "evals.jsonl"


def _assert_recorded_dataset_is_unavailable(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    dataset = manifest["dataset"]
    materialized_path = Path(dataset["materializedPath"])
    assert not materialized_path.exists()


def _forbid_dataset_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*args: object, **kwargs: object) -> object:
        raise AssertionError("dataset resolution should not be used")

    monkeypatch.setattr("ctxbench.dataset.resolver.DatasetResolver.resolve", _blocked)
    monkeypatch.setattr("ctxbench.dataset.resolver.DatasetResolver.resolve_for_planning", _blocked)
    monkeypatch.setattr("ctxbench.adapters.registry.get_default_registry", _blocked)


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


def test_export_succeeds_from_artifacts_when_dataset_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _forbid_dataset_fetch(monkeypatch)
    _forbid_dataset_resolution(monkeypatch)
    evals_path = _copy_artifact_only_fixture(tmp_path)

    _assert_recorded_dataset_is_unavailable(tmp_path)

    assert export_command(str(evals_path)) == 0
    captured = capsys.readouterr()
    assert "Exported 1 row(s)" in captured.out

    results_path = tmp_path / "results.csv"
    assert results_path.exists()
    assert "trial-artifact-only-1" in results_path.read_text(encoding="utf-8")


def test_status_succeeds_from_artifacts_when_dataset_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _forbid_dataset_fetch(monkeypatch)
    _forbid_dataset_resolution(monkeypatch)
    _copy_artifact_only_fixture(tmp_path)

    _assert_recorded_dataset_is_unavailable(tmp_path)

    assert status_command(str(tmp_path)) == 0
    captured = capsys.readouterr()
    assert "Experiment : exp-artifact-only" in captured.out
    assert "execute" in captured.out
    assert "eval" in captured.out
