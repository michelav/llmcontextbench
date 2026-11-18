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


def _keyed_experiment(models, configurations) -> AdaptiveExperiment:
    return AdaptiveExperiment(
        id="keyed", dataset={"root": str(DATASET)}, models=models,
        surfaces={"full": {"type": "full_context"}}, configurations=configurations,
        candidates=[Candidate("A", "mock", "inline")],
        workload=Workload.explicit([{"taskId": "task_role", "instanceId": "person-001"}]),
        policy=PolicyRef("static", {"candidate": "A"}), window=Window(requests=2),
    )


def test_keyed_sections_accept_a_list_of_builders_with_ids(tmp_path: Path) -> None:
    listed = _keyed_experiment([Model("mock", "mock-model", id="mock")],
                               [Configuration("inline", "json", "full", id="inline")])
    keyed = _keyed_experiment({"mock": {"provider": "mock", "name": "mock-model"}},
                              {"inline": Configuration("inline", "json", "full", id="inline")})
    assert listed == keyed
    assert listed.models == {"mock": {"provider": "mock", "name": "mock-model", "modelParams": {}}}
    assert listed.configurations == {"inline": {"strategy": "inline", "representation": "json", "surface": "full"}}
    first = plan(listed, output=tmp_path / "listed")
    second = plan(keyed, output=tmp_path / "keyed")
    for name in ("adaptive-plan.json", "resolved.json"):
        assert (first.root / name).read_bytes() == (second.root / name).read_bytes()


@pytest.mark.parametrize(("build", "message"), [
    (lambda: _keyed_experiment(
        {"other": Model("mock", "mock-model", id="mock")}, {"inline": Configuration("inline", "json", "full")}),
     "models.other: Model id 'mock' does not match its key"),
    (lambda: _keyed_experiment(
        [Model("mock", "mock-model")], {"inline": Configuration("inline", "json", "full")}),
     "a list of models takes Model builders with an id"),
    (lambda: _keyed_experiment(
        {"mock": Model("mock", "mock-model")}, [{"strategy": "inline", "representation": "json", "surface": "full"}]),
     "a list of configurations takes Configuration builders with an id"),
    (lambda: _keyed_experiment(
        [Model("mock", "a", id="mock"), Model("mock", "b", id="mock")],
        {"inline": Configuration("inline", "json", "full")}),
     "models: duplicate id 'mock'"),
    (lambda: Model("mock", "mock-model", id=""), "models: id must be a non-empty string"),
], ids=["id does not match key", "list item without id", "list item is a mapping", "duplicate id", "empty id"])
def test_keyed_sections_refuse_inconsistent_ids(build, message) -> None:
    with pytest.raises(ValueError, match=message):
        build()


def test_entry_builders_keep_id_out_of_the_entry() -> None:
    model = Model("mock", "mock-model", id="mock")
    assert "id" not in model.to_definition()
    assert Model.from_definition(model.to_definition(), id="mock") == model
    configuration = Configuration("inline", "json", "full", id="inline")
    assert Configuration.from_definition(configuration.to_definition(), id="inline") == configuration


ROUND_TRIP_CASES = [
    (Model, {"provider": "mock", "name": "model", "modelParams": {}}),
    (Model, {"provider": "mock", "name": "model", "modelParams": {"temperature": 0}}),
    (Configuration, {"strategy": "inline", "representation": "json", "surface": "full"}),
    (Candidate, {"id": "A", "model": "m", "configuration": "c"}),
    (Candidate, {"id": "A", "model": "m", "configuration": "c", "labels": {"arm": "a"}}),
    (PolicyRef, {"ref": "static", "params": {}}),
    (PolicyRef, {"ref": "pkg.mod:Policy", "params": {"x": 1}, "sources": ["table.json"]}),
    (Window, {"requests": 3, "mode": "sliding"}),
    (Window, {"requests": 3, "mode": "fixed"}),
    (Window, {"all": True, "mode": "sliding"}),
    (Window, {"all": True, "mode": "fixed"}),
    (Acceptance, {"minimumResponseLength": 0}),
    (Acceptance, {"minimumResponseLength": 5}),
    (Goal, {"id": "g", "signal": "duration_ms", "statistic": "mean", "upper": 20, "scope": "system"}),
    (Goal, {"id": "g", "signal": "failed", "statistic": "mean", "lower": 0.5, "scope": "system",
            "window": {"requests": 2, "mode": "fixed"}}),
    (SignalRef, {"id": "quality.x", "assessor": "fake"}),
    (SignalRef, {"id": "quality.x", "assessor": "fake", "sources": ["helper.py"]}),
    (Disturbance, {"name": "slow", "version": "1", "component": "model", "kind": "delay",
                   "firstSequence": 1, "seed": 0, "delayMs": 5}),
    (Disturbance, {"name": "flaky", "version": "2", "component": "local_mcp", "kind": "failure",
                   "firstSequence": 2, "lastSequence": 4, "seed": 9, "failureRate": 0.25,
                   "candidates": ["A"]}),
    (Disturbance, {"name": "both", "version": "1", "component": "model", "kind": "delay_and_failure",
                   "firstSequence": 1, "seed": 0, "delayMs": 3, "failureRate": 0.5}),
]


@pytest.mark.parametrize(("builder_type", "definition"), ROUND_TRIP_CASES,
                         ids=[f"{case[0].__name__}-{index}" for index, case in enumerate(ROUND_TRIP_CASES)])
def test_section_builder_round_trips_normalized_mappings(builder_type, definition) -> None:
    assert builder_type.from_definition(definition).to_definition() == definition


def _minimal_definition() -> dict:
    payload = _definition({"requests": [{"taskId": "task_role", "instanceId": "person-001"}]})
    payload["window"] = {"requests": 2}
    return payload


def _file_error(mutate) -> str:
    payload = _minimal_definition()
    mutate(payload)
    with pytest.raises(ValueError) as caught:
        load_adaptive_experiment(payload)
    return str(caught.value)


def _builder_error(build) -> str:
    with pytest.raises(ValueError) as caught:
        build()
    return str(caught.value)


def _field(message: str) -> str:
    """The refused field: the last path component of a schema error, or the normaliser message."""
    if " at " in message:
        path = message.split(" at ", 1)[1].split(":", 1)[0]
        # A builder has no list index or mapping key of its own; compare the named field.
        return [part for part in path.split(".") if not part.isdigit()][-1]
    return message


def _disturbance(**changes) -> dict:
    row = {"name": "d", "version": "1", "component": "model", "kind": "delay", "firstSequence": 1,
           "seed": 0, "delayMs": 5}
    row.update(changes)
    return {key: value for key, value in row.items() if value is not None}


REFUSAL_CASES = [
    ("model provider empty", lambda: Model("", "m"),
     lambda d: d["models"]["mock"].__setitem__("provider", "")),
    ("configuration surface empty", lambda: Configuration("inline", "json", ""),
     lambda d: d["configurations"]["inline"].__setitem__("surface", "")),
    ("candidate model empty", lambda: Candidate("A", "", "inline"),
     lambda d: d["candidates"]["A"].__setitem__("model", "")),
    ("policy ref empty", lambda: PolicyRef(""), lambda d: d.__setitem__("policy", {"ref": ""})),
    ("window requests zero", lambda: Window(requests=0),
     lambda d: d.__setitem__("window", {"requests": 0})),
    ("window requests and all", lambda: Window(requests=5, all=True),
     lambda d: d.__setitem__("window", {"requests": 5, "all": True})),
    ("window neither requests nor all", lambda: Window(),
     lambda d: d.__setitem__("window", {})),
    ("window bad mode", lambda: Window(requests=2, mode="tumbling"),
     lambda d: d.__setitem__("window", {"requests": 2, "mode": "tumbling"})),
    ("acceptance negative", lambda: Acceptance(-1),
     lambda d: d.__setitem__("acceptance", {"minimumResponseLength": -1})),
    ("goal with both bounds", lambda: Goal("g", "failed", "mean", upper=1, lower=0),
     lambda d: d.__setitem__("goals", [{"id": "g", "signal": "failed", "statistic": "mean",
                                        "upper": 1, "lower": 0}])),
    ("signal assessor empty", lambda: SignalRef("quality.x", ""),
     lambda d: d.__setitem__("signals", [{"id": "quality.x", "assessor": ""}])),
    ("disturbance bad component", lambda: Disturbance("d", "nope", "delay", 1, delay_ms=5),
     lambda d: d.__setitem__("disturbances", [_disturbance(component="nope")])),
    ("disturbance failure rate above one", lambda: Disturbance("d", "model", "failure", 1, failure_rate=2.0),
     lambda d: d.__setitem__("disturbances", [_disturbance(kind="failure", delayMs=None, failureRate=2.0)])),
    ("disturbance delay missing", lambda: Disturbance("d", "model", "delay", 1),
     lambda d: d.__setitem__("disturbances", [_disturbance(delayMs=None)])),
    ("disturbance zero delay", lambda: Disturbance("d", "model", "delay", 1, delay_ms=0),
     lambda d: d.__setitem__("disturbances", [_disturbance(delayMs=0)])),
    ("failure disturbance with delay", lambda: Disturbance("d", "model", "failure", 1, delay_ms=50, failure_rate=0.5),
     lambda d: d.__setitem__("disturbances", [_disturbance(kind="failure", delayMs=50, failureRate=0.5)])),
    ("disturbance inverted range", lambda: Disturbance("d", "model", "delay", 5, last_sequence=2, delay_ms=5),
     lambda d: d.__setitem__("disturbances", [_disturbance(firstSequence=5, lastSequence=2)])),
]


@pytest.mark.parametrize(("name", "build", "mutate"), REFUSAL_CASES, ids=[case[0] for case in REFUSAL_CASES])
def test_builder_refuses_what_a_file_refuses_naming_the_same_field(name, build, mutate) -> None:
    assert _field(_builder_error(build)) == _field(_file_error(mutate))


def test_builders_and_equivalent_mappings_give_equal_experiments() -> None:
    common = dict(id="eq", dataset={"root": str(DATASET)}, surfaces={"full": {"type": "full_context"}},
                  workload=Workload.explicit([{"taskId": "task_role", "instanceId": "person-001"}]))
    built = AdaptiveExperiment(
        **common, models={"mock": Model("mock", "mock-model")},
        configurations={"inline": Configuration("inline", "json", "full")},
        candidates=[Candidate("A", "mock", "inline")], policy=PolicyRef("static", {"candidate": "A"}),
        window=Window(requests=2), acceptance=Acceptance(),
        goals=(Goal("g", "failed", "mean", upper=0.5, window=Window(requests=2)),),
        disturbances=(Disturbance("slow", "model", "delay", 1, delay_ms=5),),
    )
    mapped = AdaptiveExperiment(
        **common, models={"mock": {"provider": "mock", "name": "mock-model"}},
        configurations={"inline": {"strategy": "inline", "representation": "json", "surface": "full"}},
        candidates={"A": {"model": "mock", "configuration": "inline"}},
        policy={"ref": "static", "params": {"candidate": "A"}}, window={"requests": 2},
        goals=({"id": "g", "signal": "failed", "statistic": "mean", "upper": 0.5, "window": {"requests": 2}},),
        disturbances=({"name": "slow", "version": "1", "component": "model", "kind": "delay",
                       "firstSequence": 1, "delayMs": 5},),
    )
    assert built == mapped
    assert built.window == {"requests": 2, "mode": "sliding"}
    assert built.acceptance == {"minimumResponseLength": 0}


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


FIXTURE_ROOT = ROOT / "tests/fixtures/fake_dataset"


def _every_section_file_payload() -> dict:
    return {
        "workflowKind": "adaptive", "schemaVersion": 4, "id": "every-section", "seed": 7,
        "labels": {"study": "wp-g"},
        "dataset": {"root": str(DATASET)},
        "models": {"mock": {"provider": "mock", "name": "mock-model", "modelParams": {"temperature": 0}}},
        "surfaces": {"full": {"type": "full_context"}},
        "configurations": {"inline": {"strategy": "inline", "representation": "json", "surface": "full"}},
        "candidates": {"A": {"model": "mock", "configuration": "inline", "labels": {"arm": "a"}},
                       "B": {"model": "mock", "configuration": "inline"}},
        "workload": {"generator": {"seed": 3, "segments": [{"size": 3}], "labelFeatures": ["validation_type"]}},
        "policy": {"ref": "window_threshold", "params": {
            "signal": "quality.response_quality", "statistic": "mean",
            "tiers": [{"upTo": 0.5, "select": "A"}], "otherwise": "B", "when_unavailable": "A"}},
        "window": {"all": True, "mode": "fixed"},
        "signals": [{"id": "quality.response_quality", "assessor": "online_assessor:FakeQualityAssessor"}],
        "acceptance": {"minimumResponseLength": 1},
        "goals": [{"id": "latency", "signal": "latency_ms", "statistic": "mean", "upper": 1000,
                   "window": {"requests": 2}}],
        "disturbances": [{"name": "slow", "version": "1", "component": "model", "kind": "delay",
                          "firstSequence": 2, "lastSequence": 3, "seed": 0, "delayMs": 1,
                          "candidates": ["B"]}],
    }


def _every_section_builders() -> AdaptiveExperiment:
    return AdaptiveExperiment(
        id="every-section", seed=7, labels={"study": "wp-g"}, dataset={"root": str(DATASET)},
        models={"mock": Model("mock", "mock-model", {"temperature": 0})},
        surfaces={"full": {"type": "full_context"}},
        configurations={"inline": Configuration("inline", "json", "full")},
        candidates=[Candidate("A", "mock", "inline", {"arm": "a"}), Candidate("B", "mock", "inline")],
        workload=Workload.generate(_dataset(), [Segment(3)], seed=3, label_features=["validation_type"]),
        policy=PolicyRef("window_threshold", {
            "signal": "quality.response_quality", "statistic": "mean",
            "tiers": [{"upTo": 0.5, "select": "A"}], "otherwise": "B", "when_unavailable": "A"}),
        window=Window(all=True, mode="fixed"),
        signals=(SignalRef("quality.response_quality", "online_assessor:FakeQualityAssessor"),),
        acceptance=Acceptance(1),
        goals=(Goal("latency", "latency_ms", "mean", upper=1000, window=Window(requests=2)),),
        disturbances=(Disturbance("slow", "model", "delay", 2, last_sequence=3, delay_ms=1, candidates=("B",)),),
    )


def test_builders_and_file_are_byte_identical_for_every_section(tmp_path: Path) -> None:
    definition_file = tmp_path / "definition.json"
    definition_file.write_text(json.dumps(_every_section_file_payload()), encoding="utf-8")
    file_run = plan(definition_file, output=tmp_path / "from-file", plugin_paths=[FIXTURE_ROOT])
    built_run = plan(_every_section_builders(), output=tmp_path / "from-builders", plugin_paths=[FIXTURE_ROOT])
    for name in ("adaptive-plan.json", "resolved.json"):
        assert (file_run.root / name).read_bytes() == (built_run.root / name).read_bytes(), name
    assert file_run.manifest["executionFingerprint"] == built_run.manifest["executionFingerprint"]


def test_api_round_trip_on_code_built_experiment(tmp_path: Path) -> None:
    from ctxbench.api import open_run

    run = plan(_every_section_builders(), output=tmp_path / "run", plugin_paths=[FIXTURE_ROOT])
    reopened = open_run(run.root)
    assert (reopened.kind, reopened.workflow_id) == (run.kind, run.workflow_id)
    assert reopened.manifest == run.manifest
    assert reopened.status().counts == run.status().counts
    reopened.execute(plugin_paths=[FIXTURE_ROOT])
    counts = reopened.status().counts
    assert counts["delivered"] + counts["failed"] == 3 and counts["pending"] == 0
    assert [row["requestId"] for row in run.requests()] == ["r-0001", "r-0002", "r-0003"]


def test_generator_and_explicit_expansion_differ_only_in_workload_source(tmp_path: Path) -> None:
    generated = Workload.generate(_dataset(), [Segment(5)], seed=21, label_features=["validation_type"])
    generator_run = plan(_definition(generated.to_definition()), output=tmp_path / "generator")
    generator_plan = load_json(generator_run.root / "adaptive-plan.json")
    explicit_rows = [{key: row[key] for key in ("requestId", "taskId", "instanceId", "labels")}
                     for row in generator_plan["requests"]]
    explicit_run = plan(_definition({"requests": explicit_rows}), output=tmp_path / "explicit")
    explicit_plan = load_json(explicit_run.root / "adaptive-plan.json")

    assert generator_plan["workloadSource"]["kind"] == "generated"
    assert explicit_plan["workloadSource"]["kind"] == "explicit"
    generator_plan.pop("workloadSource")
    explicit_plan.pop("workloadSource")
    assert json.dumps(generator_plan, sort_keys=True) == json.dumps(explicit_plan, sort_keys=True)


def test_feature_values_appear_only_in_request_labels(tmp_path: Path) -> None:
    dataset = _dataset()
    declared = {feature.feature_id for feature in dataset.feature_schema.features}
    labelled = {"validation_type"}
    workload = Workload.generate(dataset, [Segment(2, {"context_bytes": {"min": 0}})], seed=5,
                                 label_features=sorted(labelled))
    run = plan(_definition(workload.to_definition()), output=tmp_path / "run")
    frozen = load_json(run.root / "adaptive-plan.json")
    assert all(set(row["labels"]) == labelled for row in frozen["requests"])

    # Outside the generator specification and request labels, the plan names no feature.
    frozen.pop("workloadSource")
    for row in frozen["requests"]:
        row.pop("labels")

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    assert not declared & set(keys(frozen))


def test_code_built_example_runs_repeatedly(tmp_path: Path) -> None:
    for _ in range(2):
        output = subprocess.check_output([sys.executable, str(ROOT / "examples/adaptive/code_built.py")],
                                         cwd=tmp_path, text=True)
        assert output.startswith("Planned 4 requests at ")
    chosen = tmp_path / "chosen"
    subprocess.check_output([sys.executable, str(ROOT / "examples/adaptive/code_built.py"), str(chosen)],
                            cwd=tmp_path, text=True)
    assert (chosen / "adaptive-plan.json").is_file()
