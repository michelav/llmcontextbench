from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from ctxbench.api import (
    Acceptance, AdaptiveExperiment, Candidate, Configuration, Disturbance, Goal, Model,
    PolicyRef, Scenario, Segment, SignalRef, Window, Workload, load_dataset, plan,
)
from ctxbench.adaptive.definition import load_adaptive_experiment
from ctxbench.util.fs import load_json
from ctxbench.workload.builder import generate_requests


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "tests/fixtures/fake_dataset/dataset"


def _dataset():
    return load_dataset(DATASET)


def _definition(workload):
    return {
        "workflowKind": "adaptive", "schemaVersion": 4, "id": "generated-test",
        "dataset": {"root": str(DATASET)},
        "models": {"mock": {"provider": "mock", "name": "mock-model"}},
        "surfaces": {"full": {"type": "full_context"}},
        "configurations": {"inline": {"strategy": "inline", "representation": "json", "surface": "full"}},
        "candidates": {"A": {"model": "mock", "configuration": "inline"}},
        "workload": workload,
        "policy": {"ref": "static", "params": {"candidate": "A"}},
        "window": {"requests": 2},
    }


def test_generator_is_deterministic_across_processes() -> None:
    code = (
        "import json; from ctxbench.api import load_dataset, Segment, Workload; "
        "from ctxbench.workload.builder import generate_requests; "
        f"ds=load_dataset({str(DATASET)!r}); "
        "w=Workload.generate(ds, [Segment(8)], seed=391); "
        "print(json.dumps(generate_requests(ds, w.to_definition()['generator']), sort_keys=True))"
    )
    outputs = [subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, text=True) for _ in range(2)]
    assert outputs[0] == outputs[1]


def test_generator_filters_declared_features_labels_only_features_and_expands(tmp_path: Path) -> None:
    dataset = _dataset()
    workload = Workload.generate(
        dataset, [Segment(3, {"validation_type": "judge"})], seed=4,
        label_features=["validation_type", "task_tag_count"],
    )
    assert "generator" in workload.to_definition()
    run = plan(_definition(workload.to_definition()), output=tmp_path / "generated")
    frozen = load_json(run.root / "adaptive-plan.json")
    assert len(frozen["requests"]) == 3
    assert all(row["labels"]["validation_type"] == "judge" for row in frozen["requests"])
    assert all(isinstance(row["labels"]["task_tag_count"], str) for row in frozen["requests"])
    assert frozen["workloadSource"]["kind"] == "generated"
    assert frozen["workloadSource"]["poolDigest"]


def test_generator_and_its_explicit_expansion_freeze_identical_requests(tmp_path: Path) -> None:
    ds = _dataset()
    generated = Workload.generate(ds, [Segment(7)], seed=12, label_features=["validation_type"])
    generator_run = plan(_definition(generated.to_definition()), output=tmp_path / "generator")
    expanded = load_json(generator_run.root / "adaptive-plan.json")["requests"]
    explicit_rows = [{"requestId": row["requestId"], "taskId": row["taskId"],
                      "instanceId": row["instanceId"], "labels": row["labels"]} for row in expanded]
    explicit_run = plan(_definition({"requests": explicit_rows}), output=tmp_path / "explicit")
    assert load_json(explicit_run.root / "adaptive-plan.json")["requests"] == expanded


def test_generator_rejects_unknown_features_and_insufficient_without_replacement_pool() -> None:
    ds = _dataset()
    with pytest.raises(ValueError, match="Unknown request feature"):
        Workload.generate(ds, [Segment(1, {"not_declared": "x"})], seed=1)
    with pytest.raises(ValueError, match="exceeds its filtered pool"):
        Workload.generate(ds, [Segment(100)], seed=1, sampling="without_replacement")


def test_definition_builders_normalize_to_same_form_as_mapping(tmp_path: Path) -> None:
    workload = Workload.explicit([{"taskId": "task_role", "instanceId": "person-001"}])
    experiment = AdaptiveExperiment(
        id="builders", dataset={"root": str(DATASET)},
        models={"mock": Model("mock", "mock-model")},
        surfaces={"full": {"type": "full_context"}},
        configurations={"inline": Configuration("inline", "json", "full")},
        candidates=[Candidate("A", "mock", "inline")], workload=workload,
        policy=PolicyRef("static", {"candidate": "A"}), window=Window(requests=2),
        acceptance=Acceptance(0),
    )
    parsed = load_adaptive_experiment(experiment)
    assert parsed.workload == workload.to_definition()
    assert parsed.models == {"mock": {"provider": "mock", "name": "mock-model", "modelParams": {}}}
    assert parsed.candidates == {"A": {"model": "mock", "configuration": "inline"}}
    assert parsed.resolved_definition["workload"] == workload.to_definition()


def test_section_builder_round_trips_normalized_mappings() -> None:
    cases = [
        (Model, {"provider": "mock", "name": "model", "modelParams": {}}),
        (Configuration, {"strategy": "inline", "representation": "json", "surface": "full"}),
        (Candidate, {"id": "A", "model": "m", "configuration": "c"}),
        (PolicyRef, {"ref": "static", "params": {}}),
        (Window, {"requests": 3, "mode": "sliding"}),
        (Acceptance, {"minimumResponseLength": 0}),
        (Goal, {"id": "g", "signal": "duration_ms", "statistic": "mean", "upper": 20, "scope": "system"}),
        (SignalRef, {"id": "quality.x", "assessor": "fake", "sources": ["helper.py"]}),
        (Disturbance, {"name": "slow", "version": "1", "component": "model", "kind": "delay",
                       "firstSequence": 1, "seed": 0, "delayMs": 5}),
    ]
    for builder_type, definition in cases:
        builder = builder_type.from_definition(definition)
        assert builder.to_definition() == definition
    all_window = Window.from_definition({"all": True})
    assert all_window.to_definition() == {"all": True}
    with pytest.raises(ValueError, match="models."):
        Model("", "")


def test_scenario_returns_only_workload_and_disturbance_sections() -> None:
    scenario = Scenario(Workload.explicit([{"taskId": "task_role", "instanceId": "person-001"}]),
                        (Disturbance("slow", "model", "delay", 1, delay_ms=5),))
    sections = scenario.to_sections()
    assert set(sections) == {"workload", "disturbances"}
    assert sections["workload"]["requests"][0]["taskId"] == "task_role"
    assert sections["disturbances"][0]["delayMs"] == 5


def test_builder_and_file_planning_are_byte_identical(tmp_path: Path) -> None:
    request_workload = Workload.explicit([{"requestId": "r-0001", "taskId": "task_role",
                                           "instanceId": "person-001"}])
    payload = _definition(request_workload.to_definition())
    definition_file = tmp_path / "definition.json"
    definition_file.write_text(json.dumps(payload), encoding="utf-8")
    file_run = plan(definition_file, output=tmp_path / "from-file")
    from_object = load_adaptive_experiment(payload, base_dir=tmp_path)
    object_run = plan(from_object, output=tmp_path / "from-object")
    assert (file_run.root / "adaptive-plan.json").read_bytes() == (object_run.root / "adaptive-plan.json").read_bytes()
    assert (file_run.root / "resolved.json").read_bytes() == (object_run.root / "resolved.json").read_bytes()
    assert load_json(file_run.root / "manifest.json")["executionFingerprint"] == \
        load_json(object_run.root / "manifest.json")["executionFingerprint"]
