from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ctxbench.adaptive.sensors import AssessmentInput, QualityObservation, assess_quality, resolve_quality_assessors
from ctxbench.adapters.repoqa.package import RepoQADatasetAdapter
from ctxbench.api import ExecutionStateError, plan
from ctxbench.core.provenance import Provenance
from ctxbench.util.fs import load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/fake_dataset"
DATASET = FIXTURE_ROOT / "dataset"


def _definition(*, assessor: str = "online_assessor:FakeQualityAssessor", request_count: int = 2):
    value = json.loads((ROOT / "examples/adaptive/minimal.json").read_text(encoding="utf-8"))
    value["dataset"]["root"] = str(DATASET.resolve())
    value["candidates"] = {
        "A": {"model": "mock", "configuration": "inline-json"},
        "B": {"model": "mock", "configuration": "inline-json"},
    }
    value["workload"]["requests"] = [
        {"requestId": f"q-{index:04}", "taskId": "task_role", "instanceId": "person-001"}
        for index in range(1, request_count + 1)
    ]
    value["signals"] = [{"id": "quality.response_quality", "assessor": assessor}]
    value["policy"] = {
        "ref": "window_threshold",
        "params": {
            "signal": "quality.response_quality", "statistic": "mean",
            "tiers": [{"upTo": 0.5, "select": "A"}],
            "otherwise": "B", "when_unavailable": "A",
        },
    }
    return value


def test_quality_signal_is_persisted_and_available_to_policy_and_metrics(tmp_path: Path):
    run = plan(_definition(), output=tmp_path / "quality-run", plugin_paths=[FIXTURE_ROOT])
    frozen = load_json(run.root / "adaptive-plan.json")
    signal = frozen["signals"][0]
    assert signal["metricId"] == "response_quality"
    assert signal["assessorVersion"] == "1"
    assert signal["sourceDigest"]
    assert run.manifest["fingerprintInputs"]["plugins"][-1] == {
        "ref": "online_assessor:FakeQualityAssessor", "sourceDigest": signal["sourceDigest"],
    }
    assert run.manifest["privileged"] is False

    # Offline evaluation rows are not an input to execution or policy decisions.
    (run.root / "evals.jsonl").write_text(
        '{"requestId":"q-0001","outcome":{"quality.response_quality":0}}\n', encoding="utf-8",
    )
    run.execute(plugin_paths=[FIXTURE_ROOT])
    records = [load_json(run.root / "adaptive-records" / f"q-{index:04}.json")
               for index in (1, 2)]
    assert [row["attempts"][0]["decision"]["candidateId"] for row in records] == ["A", "B"]
    first_attempt = records[0]["attempts"][0]
    quality = first_attempt["observation"]["signals"]["quality.response_quality"]
    assert quality == {"value": 1.0, "provenance": "derived", "unit": "binary"}
    assert first_attempt["assessorCost"][0]["durationProvenance"] == "measured"
    assert first_attempt["assessorCost"][0]["totalTokens"] == 0

    outcome = run.metrics(output=tmp_path / "metrics")
    assert outcome.counts["requests"] == 2
    with (outcome.output_dir / "adaptive_attempt_metrics.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["assessorTokenProvenance"] == "derived"
    assert rows[0]["assessorDurationProvenance"] == "measured"
    assert rows[0]["assessorTotalTokens"] == "0"
    metrics_manifest = load_json(outcome.output_dir / "metrics-manifest.json")
    assert metrics_manifest["privileged"] is False


def test_assessor_failure_becomes_unavailable_with_measured_cost():
    class FailingAssessor:
        def __init__(self, capability):
            self.capability = capability
        def assess(self, _item):
            raise RuntimeError("synthetic assessor error")

    class Package:
        def capability_report(self):
            from types import SimpleNamespace
            return SimpleNamespace(semantic_quality_assessors=())

    # Exercise the normal resolution path with a tiny class reference and replace only its method.
    resolved = resolve_quality_assessors(
        [{"id": "quality.response_quality", "assessor": "online_assessor:FakeQualityAssessor"}],
        Package(), plugin_paths=[FIXTURE_ROOT],
    )[0]
    failed = type(resolved)(resolved.signal, FailingAssessor(resolved.capability), resolved.capability)
    ticks = iter((1.0, 1.002))
    observation, cost = assess_quality(
        failed,
        AssessmentInput("q-1", "task_role", "person-001", "A", "answer"),
        clock=lambda: next(ticks),
    )
    assert observation.value is None
    assert observation.provenance == Provenance.UNAVAILABLE
    assert observation.cost.duration_ms == pytest.approx(2.0)
    assert observation.cost.duration_provenance == Provenance.MEASURED
    assert cost["errorType"] == "RuntimeError"
    assert cost["totalTokens"] is None


def test_dataset_capability_resolves_its_online_assessor():
    package = RepoQADatasetAdapter(ROOT / "tests/fixtures/repoqa_tools_dataset")
    resolved = resolve_quality_assessors(
        [{"id": "quality.repoqa_correctness", "assessor": "repoqa-reference-scorer"}], package,
    )
    assert resolved[0].capability.uses_reference_data is True
    assert resolved[0].assessor.capability == resolved[0].capability


def test_assessor_failure_is_unavailable_to_the_next_policy_decision(tmp_path: Path):
    definition = _definition(assessor="online_assessor:FailingQualityAssessor")
    run = plan(definition, output=tmp_path / "unavailable-quality", plugin_paths=[FIXTURE_ROOT])
    run.execute(plugin_paths=[FIXTURE_ROOT])
    first = load_json(run.root / "adaptive-records" / "q-0001.json")["attempts"][0]
    second = load_json(run.root / "adaptive-records" / "q-0002.json")["attempts"][0]
    quality = first["observation"]["signals"]["quality.response_quality"]
    assert quality["value"] is None
    assert quality["provenance"] == "unavailable"
    assert first["assessorCost"][0]["errorType"] == "RuntimeError"
    assert second["decision"]["candidateId"] == "A"  # when_unavailable


def test_reference_data_assessor_marks_run_and_metrics_privileged(tmp_path: Path):
    run = plan(_definition(assessor="online_assessor:FakeReferenceAssessor", request_count=1),
               output=tmp_path / "privileged-run", plugin_paths=[FIXTURE_ROOT])
    assert run.manifest["privileged"] is True
    run.execute(plugin_paths=[FIXTURE_ROOT])
    outcome = run.metrics(output=tmp_path / "privileged-metrics")
    assert load_json(outcome.output_dir / "metrics-manifest.json")["privileged"] is True
    with (outcome.output_dir / "adaptive_request_metrics.csv").open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["privileged"] == "True"


def test_resume_reuses_persisted_quality_observation_without_assessing_twice(tmp_path: Path, monkeypatch):
    import ctxbench.adaptive.workflow as workflow_module

    run = plan(_definition(request_count=1), output=tmp_path / "quality-resume", plugin_paths=[FIXTURE_ROOT])
    real_write = workflow_module.write_json
    real_assess = workflow_module.assess_quality
    calls = 0

    def count_assess(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_assess(*args, **kwargs)

    def interrupt_before_request_record(path, value):
        if Path(path).parent.name == "adaptive-records" and value.get("state") == "delivered":
            raise RuntimeError("simulated interruption after durable execution")
        return real_write(path, value)

    monkeypatch.setattr(workflow_module, "assess_quality", count_assess)
    monkeypatch.setattr(workflow_module, "write_json", interrupt_before_request_record)
    with pytest.raises(RuntimeError, match="after durable execution"):
        run.execute(plugin_paths=[FIXTURE_ROOT])
    assert calls == 1

    monkeypatch.setattr(workflow_module, "write_json", real_write)
    run.execute(plugin_paths=[FIXTURE_ROOT])
    assert calls == 1
    record = load_json(run.root / "adaptive-records" / "q-0001.json")
    assert record["attempts"][0]["observation"]["signals"]["quality.response_quality"]["value"] == 1.0


def test_external_assessor_source_changes_are_refused(tmp_path: Path):
    plugin = tmp_path / "quality_plugins"
    plugin.mkdir()
    source = (FIXTURE_ROOT / "online_assessor.py").read_text(encoding="utf-8")
    (plugin / "online_assessor.py").write_text(source, encoding="utf-8")
    run = plan(_definition(request_count=1), output=tmp_path / "changed-plugin-run", plugin_paths=[plugin])
    (plugin / "online_assessor.py").write_text(source + "\n# changed after planning\n", encoding="utf-8")
    with pytest.raises(ExecutionStateError, match="Online assessor source changed"):
        run.execute(plugin_paths=[plugin])
