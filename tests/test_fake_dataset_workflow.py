from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxbench.ai.engine import Engine
from ctxbench.benchmark import evaluation as evaluation_module
from ctxbench.benchmark.evaluation import EvaluationTrace
from ctxbench.commands.plan import plan_command
from ctxbench.commands.execute import execute_command
from ctxbench.commands.eval import eval_command
from ctxbench.commands.export import export_command
from ctxbench.commands.metrics import metrics_command
from ctxbench.commands.status import status_command
from ctxbench.dataset.cache import DatasetCache
from ctxbench.dataset.materialization import MaterializationManifest
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.dataset.resolver import DatasetResolver
from ctxbench.util.jsonl import read_jsonl


REPO_ROOT = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.workflow, pytest.mark.e2e]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "fake_dataset"
EXPERIMENT_PATH = FIXTURE_ROOT / "experiment.json"
DATASET_ROOT = FIXTURE_ROOT / "dataset"
FORBIDDEN_TERMS = ("lattes", "curriculum", "lattesprovider")


def _cached_manifest(origin: str) -> MaterializationManifest:
    return MaterializationManifest(
        datasetId="ctxbench/fake-dataset",
        requestedVersion="0.1.0",
        datasetVersion="0.1.0",
        resolvedRevision="fixture-rev",
        origin=origin,
        materializedPath="",
        contentHash="sha256:fixture",
        fetchedAt="2026-05-12T00:00:00Z",
        ctxbenchVersion="0.1.0",
        fetchMethod="file-copy",
        sourceType="local-directory",
        archiveUrl=None,
        releaseTagUrl=None,
        assetName=None,
        verifiedSha256=None,
    )


def test_fake_dataset_plan_workflow_is_provider_free(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(REPO_ROOT)

    provider_calls = {"engine_execute": 0}

    def fail_execute(self: Engine, *args: object, **kwargs: object) -> object:
        del self, args, kwargs
        provider_calls["engine_execute"] += 1
        raise AssertionError("Planning must not execute provider-backed model calls.")

    monkeypatch.setattr(Engine, "execute", fail_execute)

    cache = DatasetCache(cache_dir=tmp_path / "cache")
    resolver = DatasetResolver()
    package = resolver.resolve({"root": str(DATASET_ROOT)}, cache)

    assert isinstance(package, LocalDatasetPackage)
    assert package.identity() == "ctxbench/fake-dataset"
    assert package.version() == "0.1.0"
    assert package.list_instance_ids() == ["person-001"]
    assert package.list_task_ids() == ["task_role"]

    output_root = tmp_path / "planned"
    assert plan_command(str(EXPERIMENT_PATH), output=str(output_root), cache_dir=tmp_path / "cache") == 0

    trials = read_jsonl(output_root / "trials.jsonl")
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))

    assert len(trials) == 1
    assert trials[0]["taskId"] == "task_role"
    assert "questionId" not in trials[0]
    assert trials[0]["dataset"]["id"] == "ctxbench/fake-dataset"
    assert trials[0]["taskStatement"] == "What role does Avery Example have?"

    serialized_trials = json.dumps(trials, ensure_ascii=False).lower()
    for term in FORBIDDEN_TERMS:
        assert term not in serialized_trials

    assert manifest["dataset"]["id"] == "ctxbench/fake-dataset"
    assert provider_calls["engine_execute"] == 0


def test_fake_dataset_plan_workflow_uses_env_cache_root_for_cached_dataset(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    custom_cache_root = tmp_path / "custom-cache"
    cache = DatasetCache(cache_dir=custom_cache_root)
    cache.store(_cached_manifest(str(DATASET_ROOT)), DATASET_ROOT)
    monkeypatch.setenv("CTXBENCH_DATASET_CACHE", str(custom_cache_root))

    experiment_path = tmp_path / "cached-experiment.json"
    experiment_path.write_text(
        json.dumps(
            {
                "schemaVersion": 3,
                "kind": "benchmark",
                "id": "exp-fake-cached",
                "output": "outputs",
                "dataset": {"id": "ctxbench/fake-dataset", "version": "0.1.0"},
                "scope": {"instances": [], "tasks": []},
                "models": {"mock": {"provider": "mock", "name": "mock"}},
                "configurations": {'inline-json': {'strategy': 'inline', 'representation': 'json', 'surface': 'full'}},
                "surfaces": {"full": {"type": "full_context"}},
                "candidates": [["mock", "inline-json"]],
                "evaluation": {"enabled": False, "judges": []},
            }
        ),
        encoding="utf-8",
    )

    output_root = tmp_path / "planned-cached"
    assert plan_command(str(experiment_path), output=str(output_root)) == 0

    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"]["id"] == "ctxbench/fake-dataset"
    assert manifest["dataset"]["materializedPath"]


def test_fake_dataset_static_benchmark_lifecycle_preserves_assignments(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    output_root = tmp_path / "benchmark"
    experiment = json.loads(EXPERIMENT_PATH.read_text(encoding="utf-8"))
    experiment["dataset"]["root"] = str(DATASET_ROOT.resolve())
    experiment["evaluation"] = {
        "enabled": True,
        "judges": [{"provider": "mock", "model": "mock-judge"}],
    }
    versioned_experiment = tmp_path / "experiment-v3.json"
    versioned_experiment.write_text(json.dumps(experiment), encoding="utf-8")
    assert plan_command(
        str(versioned_experiment), output=str(output_root), cache_dir=tmp_path / "cache"
    ) == 0
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["provisioningArtifactVersion"] == 4

    trial_rows = read_jsonl(output_root / "trials.jsonl")
    assert trial_rows
    assignments = {
        row["trialId"]: (row["configurationId"], row["strategy"], row["representation"])
        for row in trial_rows
    }

    assert execute_command(str(output_root / "trials.jsonl")) == 0
    response_rows = read_jsonl(output_root / "responses.jsonl")
    assert {row["trialId"] for row in response_rows} == set(assignments)
    assert {
        row["trialId"]: (row["configurationId"], row["strategy"], row["representation"])
        for row in response_rows
    } == assignments

    def fake_judge_request(**kwargs):
        config = kwargs["config"]
        return (
            {
                "correctness": {"rating": "meets", "justification": "fixture"},
                "completeness": {"rating": "meets", "justification": "fixture"},
            },
            evaluation_module.EvaluationJudgeInfo(
                used=True, role="judge", provider=config.provider, model=config.model
            ),
            EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)
    assert eval_command(str(output_root / "responses.jsonl")) == 0
    eval_rows = read_jsonl(output_root / "evals.jsonl")
    assert len(eval_rows) == len(response_rows)
    assert {row["trialId"] for row in eval_rows} == set(assignments)
    assert export_command(str(output_root / "evals.jsonl")) == 0
    assert (output_root / "results.csv").exists()
    assert metrics_command([str(output_root)]) == 0
    assert (output_root / "metrics" / "trial_metrics.csv").exists()
    assert status_command(str(output_root)) == 0
    status_output = capsys.readouterr().out
    assert "execute" in status_output
    assert "eval" in status_output
