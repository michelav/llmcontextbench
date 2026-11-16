from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxbench.api import (
    CtxbenchError, DefinitionError, ExecuteOutcome, ExecutionStateError, MetricsOutcome,
    PhaseOutcome, Run, RunNotFoundError, RunStatus, open_run, plan,
)
from ctxbench.api.workflows import registry
from ctxbench.core.workflow import Workflow


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = REPO_ROOT / "tests/fixtures/fake_dataset/experiment.json"
DATASET = REPO_ROOT / "tests/fixtures/fake_dataset/dataset"
ADAPTIVE = REPO_ROOT / "examples/adaptive/minimal.json"


def _benchmark_definition() -> dict:
    definition = json.loads(EXPERIMENT.read_text(encoding="utf-8"))
    definition["dataset"]["root"] = str(DATASET.resolve())
    return definition


def _silent(capsys) -> bool:
    captured = capsys.readouterr()
    return captured.out == "" and captured.err == ""


def test_registry_resolves_kinds_for_definitions_and_runs(tmp_path: Path) -> None:
    assert registry.for_definition({"schemaVersion": 3}).kind == "benchmark"
    assert registry.for_definition({"workflowKind": "adaptive"}).kind == "adaptive"
    assert registry.for_run(tmp_path).kind == "benchmark"   # missing manifest: default reports it
    with pytest.raises(ValueError, match="unsupported workflow kind"):
        registry.for_definition({"workflowKind": "other"})
    for kind in ("benchmark", "adaptive"):
        workflow = registry.get(kind)
        for name in Workflow.__dict__:
            if not name.startswith("_") and name != "kind":
                assert callable(getattr(workflow, name)), f"{kind} lacks {name}"


def test_benchmark_lifecycle_through_api_is_silent_and_typed(tmp_path: Path, capsys) -> None:
    run = plan(_benchmark_definition(), output=tmp_path / "run", cache_dir=tmp_path / "cache")

    assert isinstance(run, Run) and run.kind == "benchmark"
    status = run.status()
    assert isinstance(status, RunStatus) and status.counts["planned"] > 0 and status.report
    assert len(list(run.trials())) == status.counts["planned"]

    outcome = run.execute()
    assert isinstance(outcome, ExecuteOutcome)
    assert outcome.counts["processed"] == status.counts["planned"]
    assert run.execute().counts["skipped"] == status.counts["planned"]
    assert len(list(run.responses())) == status.counts["planned"]

    # The fixture declares no judges: the evaluation phase is reached and reports it as an error.
    with pytest.raises(ExecutionStateError, match="No judges matched"):
        run.evaluate()
    exported = run.export()
    assert isinstance(exported, PhaseOutcome) and (run.root / "results.csv").is_file()
    metrics = run.metrics()
    assert isinstance(metrics, MetricsOutcome) and metrics.output_dir == run.root / "metrics"
    assert run.metric_tables()["trials"]

    reopened = open_run(run.root)
    assert (reopened.kind, reopened.workflow_id) == (run.kind, run.workflow_id)
    assert reopened.manifest["experimentId"] == run.workflow_id
    with pytest.raises(ExecutionStateError):
        run.requests()
    assert _silent(capsys)


def test_plan_from_path_matches_cli_planning(tmp_path: Path, capsys) -> None:
    from ctxbench.commands.plan import plan_command

    definition_path = tmp_path / "experiment.json"
    definition_path.write_text(json.dumps(_benchmark_definition()), encoding="utf-8")
    run = plan(definition_path, output=tmp_path / "api", cache_dir=tmp_path / "cache")
    assert _silent(capsys)
    assert plan_command(str(definition_path), output=str(tmp_path / "cli"), cache_dir=tmp_path / "cache") == 0
    assert "Planned" in capsys.readouterr().out
    assert (run.root / "trials.jsonl").read_text() == (tmp_path / "cli" / "trials.jsonl").read_text()


def test_in_memory_definition_resolves_relative_paths_against_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    definition = _benchmark_definition()
    run = plan(definition, cache_dir=tmp_path / "cache")
    assert tmp_path in run.root.parents
    assert run.manifest["experimentPath"] is None
    with pytest.raises(DefinitionError, match="extends"):
        plan({**definition, "extends": "base.json"}, output=tmp_path / "other")


def test_adaptive_lifecycle_through_api_is_silent_and_typed(tmp_path: Path, capsys) -> None:
    run = plan(ADAPTIVE, output=tmp_path / "run")

    assert run.kind == "adaptive"
    assert run.status().counts["planned"] == 1
    assert [row["state"] for row in run.requests()] == ["pending"]

    outcome = run.execute()
    assert outcome.counts == {"delivered": 1, "failed": 0, "started": 0}
    assert [row["state"] for row in run.requests()] == ["delivered"]
    assert len(list(run.attempts())) == 1
    assert len(list(run.responses())) == 1
    assert set(run.metric_tables()) == {"requests", "attempts"}
    assert run.metrics().counts == {"requests": 1, "attempts": 1}
    assert run.export().messages
    assert open_run(run.root).kind == "adaptive"
    with pytest.raises(ExecutionStateError):
        run.trials()
    assert _silent(capsys)


def test_api_reports_failures_as_ctxbench_errors(tmp_path: Path) -> None:
    with pytest.raises(RunNotFoundError):
        open_run(tmp_path / "missing")
    with pytest.raises(DefinitionError):
        plan({"workflowKind": "adaptive"}, output=tmp_path / "invalid")
    run = plan(ADAPTIVE, output=tmp_path / "run")
    with pytest.raises(ExecutionStateError, match="fresh output directory"):
        plan(ADAPTIVE, output=tmp_path / "run")
    with pytest.raises(ExecutionStateError, match="--force is not supported"):
        run.execute(force=True)
    with pytest.raises(CtxbenchError):
        run.status(by="strategy")
