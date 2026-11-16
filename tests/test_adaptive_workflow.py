from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxbench.adaptive.artifacts import adaptive_plan_from_payload, adaptive_plan_payload
from ctxbench.adaptive.definition import AdaptiveExperiment, WorkloadRequest, load_adaptive_experiment
from ctxbench.adaptive.policy import CandidateRef
from ctxbench.adaptive.plan import WindowSpec
from ctxbench.adaptive.state import Observation, WindowSystemState
from ctxbench.adaptive.testing import verify_replay
from ctxbench.api import ArtifactError, CapabilityError, DefinitionError, ExecutionStateError, open_run, plan
from ctxbench.execution.service import TrialExecutionService
from ctxbench.util.fs import load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/adaptive/minimal.json"
DATASET = ROOT / "tests/fixtures/fake_dataset/dataset"


def _definition(*, request_count: int = 1, policy: dict | None = None) -> dict:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value["dataset"]["root"] = str(DATASET.resolve())
    value["candidates"] = {
        "A": {"model": "mock", "configuration": "inline-json", "labels": {"arm": "A"}},
        "B": {"model": "mock", "configuration": "inline-json", "labels": {"arm": "B"}},
    }
    value["workload"]["requests"] = [
        {"requestId": f"r-{index:04}", "taskId": "task_role", "instanceId": "person-001",
         "labels": {"position": str(index)}}
        for index in range(1, request_count + 1)
    ]
    value["policy"] = policy or {"ref": "static", "params": {"candidate": "A"}}
    value["seed"] = 391
    return value


def _decision_rows(root: Path) -> list[dict]:
    records = sorted((root / "adaptive-records").glob("*.json"))
    return [load_json(path)["attempts"][0]["decision"] for path in records]


def test_adaptive_definition_parses_as_one_object_model_and_round_trips_plan(tmp_path: Path) -> None:
    payload = _definition(request_count=3)
    definition_path = tmp_path / "definition.json"
    definition_path.write_text(json.dumps(payload), encoding="utf-8")

    from_file = load_adaptive_experiment(definition_path)
    from_object = load_adaptive_experiment(payload, base_dir=tmp_path)
    assert isinstance(from_file, AdaptiveExperiment)
    assert from_file == from_object

    path_run = plan(definition_path, output=tmp_path / "path-run")
    object_run = plan(payload, output=tmp_path / "object-run")
    model_run = plan(from_file, output=tmp_path / "model-run")
    path_plan = load_json(path_run.root / "adaptive-plan.json")
    object_plan = load_json(object_run.root / "adaptive-plan.json")
    assert path_plan == object_plan
    assert load_json(model_run.root / "adaptive-plan.json") == path_plan
    assert adaptive_plan_payload(adaptive_plan_from_payload(path_plan)) == path_plan
    assert len(path_plan["candidates"]) == 2
    assert "candidates" not in path_plan["requests"][0]
    assert "execution" not in path_plan["requests"][0]


def test_schema_v3_plan_is_rejected_with_fresh_plan_guidance() -> None:
    with pytest.raises(ValueError, match="create a fresh adaptive plan"):
        adaptive_plan_from_payload({"schemaVersion": 3})


def test_builtin_static_random_and_round_robin_policies_are_deterministic(tmp_path: Path) -> None:
    random_definition = _definition(request_count=12, policy={
        "ref": "random", "params": {"candidates": ["A", "B"]},
    })
    first = plan(random_definition, output=tmp_path / "random-1")
    second = plan(random_definition, output=tmp_path / "random-2")
    first.execute()
    second.execute()
    first_choices = [row["candidateId"] for row in _decision_rows(first.root)]
    second_choices = [row["candidateId"] for row in _decision_rows(second.root)]
    assert first_choices == second_choices
    assert set(first_choices) == {"A", "B"}
    assert verify_replay(first.root) == []

    rr = plan(_definition(request_count=4, policy={"ref": "round_robin", "params": {}}),
              output=tmp_path / "round-robin")
    rr.execute()
    assert [row["candidateId"] for row in _decision_rows(rr.root)] == ["A", "B", "A", "B"]


def test_adaptive_cli_plans_and_executes_a_v4_definition(tmp_path: Path, capsys) -> None:
    from ctxbench.commands.execute import execute_command
    from ctxbench.commands.plan import plan_command

    definition_path = tmp_path / "adaptive.json"
    definition_path.write_text(json.dumps(_definition()), encoding="utf-8")
    root = tmp_path / "cli-run"
    assert plan_command(str(definition_path), output=str(root)) == 0
    assert execute_command(str(root / "adaptive-plan.json")) == 0
    record = load_json(root / "adaptive-records" / "r-0001.json")
    assert record["state"] == "delivered"
    assert len(record["attempts"]) == 1
    assert capsys.readouterr().out


def test_policy_inputs_expose_only_candidate_catalogue_and_prior_outcomes() -> None:
    candidate = CandidateRef("A", {"arm": "static-label"})
    state = WindowSystemState(
        decision_index=2,
        observations=[Observation(1, "B", "error", "unknown", {})],
        memo={"position": 1}, seed=5, decision_id="request-2:d1", default_window=WindowSpec(2),
        candidate_ids=("A", "B"),
    )
    assert {field for field in dir(candidate) if not field.startswith("_")} == {"candidate_id", "labels"}
    assert {field for field in dir(state) if not field.startswith("_")} == {
        "candidate", "completed_requests", "decision_index", "default_window", "memo", "reading_audit",
        "rng", "window",
    }
    assert state.candidate("B").last_status == "error"
    assert not any(hasattr(state, field) for field in
                   ("request_id", "task_id", "instance_id", "labels", "task_statement", "context_bytes"))
    reading = state.window("failed.context_overflow", "rate")
    assert not any(hasattr(reading, field) for field in
                    ("request_id", "task_id", "instance_id", "labels", "context_bytes"))


def test_failed_delivery_keeps_one_attempt_and_does_not_fallback(tmp_path: Path) -> None:
    definition = _definition(policy={"ref": "static", "params": {"candidate": "A"}})
    definition["acceptance"] = {"minimumResponseLength": 10000}
    run = plan(definition, output=tmp_path / "failed")
    outcome = run.execute()

    assert outcome.counts["failed"] == 1
    record = load_json(run.root / "adaptive-records" / "r-0001.json")
    assert record["state"] == "failed"
    assert record["terminalReason"] == "response_too_short"
    assert len(record["attempts"]) == 1
    assert record["attempts"][0]["decision"]["candidateId"] == "A"
    assert len(TrialExecutionService(run.root).attempts("r-0001")) == 1
    assert list(run.responses()) == []


def test_resume_reuses_persisted_decision_without_calling_policy_again(tmp_path: Path, monkeypatch) -> None:
    import ctxbench.adaptive.workflow as adaptive_workflow

    run = plan(_definition(), output=tmp_path / "resume")
    real_execute = TrialExecutionService.execute

    def interrupt_after_decision(self, request, session, invoke, **kwargs):
        del self, request, session, invoke, kwargs
        raise RuntimeError("simulated interruption after decision persistence")

    monkeypatch.setattr(TrialExecutionService, "execute", interrupt_after_decision)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        run.execute()
    saved = load_json(run.root / "adaptive-records" / "r-0001.json")
    assert saved["state"] == "started"
    assert saved["attempts"][0]["decision"]["candidateId"] == "A"

    monkeypatch.setattr(adaptive_workflow, "resolve_policy",
                        lambda *args, **kwargs: pytest.fail("completed decision was recomputed"))
    monkeypatch.setattr(TrialExecutionService, "execute", real_execute)
    assert run.execute().counts["delivered"] == 1
    assert len(load_json(run.root / "adaptive-records" / "r-0001.json")["attempts"]) == 1


def test_external_policy_is_fingerprinted_and_change_requires_fresh_plan(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    module = plugin_dir / "test_policy.py"
    module.write_text(
        "from ctxbench.api import Decision\n"
        "class ChooseA:\n"
        "    id = 'choose_a'\n"
        "    version = '1'\n"
        "    def __init__(self): pass\n"
        "    def decide(self, candidates, state):\n"
        "        return Decision('A', 'choose A')\n",
        encoding="utf-8",
    )
    definition = _definition(policy={"ref": "test_policy:ChooseA", "params": {}})
    run = plan(definition, output=tmp_path / "plugged", plugin_paths=[plugin_dir])
    module.write_text(module.read_text(encoding="utf-8").replace("choose A", "choose A changed"), encoding="utf-8")

    with pytest.raises(ExecutionStateError, match="Policy source changed.*fresh adaptive plan"):
        run.execute(plugin_paths=[plugin_dir])
    assert not list((run.root / "adaptive-records").glob("*.json"))


def test_invalid_policy_decision_stops_before_attempt_creation(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "bad_policy.py").write_text(
        "from ctxbench.api import Decision\n"
        "class Invalid:\n"
        "    id = 'invalid'\n"
        "    version = '1'\n"
        "    def __init__(self): pass\n"
        "    def decide(self, candidates, state):\n"
        "        return Decision('missing', 'invalid candidate')\n",
        encoding="utf-8",
    )
    definition = _definition(policy={"ref": "bad_policy:Invalid", "params": {}})
    run = plan(definition, output=tmp_path / "invalid", plugin_paths=[plugin_dir])
    with pytest.raises(ExecutionStateError, match="unknown candidate"):
        run.execute(plugin_paths=[plugin_dir])
    record = load_json(run.root / "adaptive-records" / "r-0001.json")
    assert record["state"] == "started" and record["attempts"] == []
    assert not list((run.root / "execution-records").glob("**/*.json"))


def test_experiment_object_built_in_a_script_plans_and_executes(tmp_path: Path) -> None:
    payload = _definition(request_count=2)
    experiment = AdaptiveExperiment(
        id="scripted", dataset=payload["dataset"], models=payload["models"], surfaces=payload["surfaces"],
        configurations=payload["configurations"], candidates=payload["candidates"],
        workload=(WorkloadRequest("task_role", "person-001"), WorkloadRequest("task_role", "person-001")),
        policy={"ref": "round_robin"}, window={"requests": 5},
    )
    run = plan(experiment, output=tmp_path / "scripted")

    assert run.kind == "adaptive"
    resolved = load_json(run.root / "resolved.json")
    assert resolved["id"] == "scripted" and resolved["policy"] == {"ref": "round_robin"}
    assert run.execute().counts["delivered"] == 2
    assert [row["candidateId"] for row in _decision_rows(run.root)] == ["A", "B"]


def test_definition_problems_found_while_planning_are_definition_errors(tmp_path: Path) -> None:
    mixed = _definition()
    mixed["models"]["other"] = {"provider": "mock", "name": "other"}
    mixed["candidates"]["B"]["model"] = "other"
    unknown_target = _definition(policy={"ref": "static", "params": {"candidate": "missing"}})
    unknown_policy = _definition(policy={"ref": "no_such_policy"})

    for index, (definition, message) in enumerate([
        (mixed, "one model"), (unknown_target, "unknown candidates"), (unknown_policy, "Unknown built-in policy"),
    ]):
        with pytest.raises(DefinitionError, match=message):
            plan(definition, output=tmp_path / f"invalid-{index}")
        assert not (tmp_path / f"invalid-{index}").exists()


def test_candidate_strategy_the_dataset_cannot_serve_is_refused_at_plan(tmp_path: Path) -> None:
    for strategy, message in (("local_function", "tool_provider"), ("remote_mcp", "MCP server settings")):
        definition = _definition()
        definition["configurations"]["other"] = {"strategy": strategy, "representation": "json", "surface": "full"}
        definition["candidates"]["B"]["configuration"] = "other"
        with pytest.raises(CapabilityError, match=message):
            plan(definition, output=tmp_path / strategy)
        assert not (tmp_path / strategy).exists()


def test_run_with_external_policy_survives_moving_run_and_plugin_directories(tmp_path: Path) -> None:
    import sys

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "movable_policy.py").write_text(
        "from ctxbench.api import Decision\n"
        "class ChooseB:\n"
        "    id = 'choose_b'\n"
        "    version = '1'\n"
        "    def __init__(self): pass\n"
        "    def decide(self, candidates, state):\n"
        "        return Decision('B', 'choose B')\n",
        encoding="utf-8",
    )
    (plugin_dir / "table.json").write_text("{}", encoding="utf-8")
    definition = _definition(policy={"ref": "movable_policy:ChooseB", "params": {},
                                     "sources": [str(plugin_dir / "table.json")]})
    run = plan(definition, output=tmp_path / "run", plugin_paths=[plugin_dir])
    recorded = load_json(run.root / "adaptive-plan.json")["policy"]
    assert recorded["sources"] == ["table.json"]
    assert str(tmp_path) not in json.dumps(recorded)

    (tmp_path / "run").rename(tmp_path / "run-moved")
    plugin_dir.rename(tmp_path / "plugins-moved")
    sys.modules.pop("movable_policy", None)   # a new process would import from the new location
    moved = open_run(tmp_path / "run-moved")
    assert moved.execute(plugin_paths=[tmp_path / "plugins-moved"]).counts["delivered"] == 1

    (tmp_path / "plugins-moved" / "table.json").write_text('{"changed": true}', encoding="utf-8")
    sys.modules.pop("movable_policy", None)
    with pytest.raises(ExecutionStateError, match="Policy source changed"):
        moved.execute(plugin_paths=[tmp_path / "plugins-moved"])


def test_status_groups_requests_by_decided_candidate(tmp_path: Path) -> None:
    run = plan(_definition(request_count=3, policy={"ref": "round_robin"}), output=tmp_path / "status")
    run.execute()

    report = "\n".join(run.status(by="candidate").report)
    rows = {line.split()[0]: line.split()[1:] for line in report.splitlines() if line[:1] in {"A", "B"}}
    assert rows == {"A": ["2", "2", "0", "0"], "B": ["1", "1", "0", "0"]}
    assert "task_role" in "\n".join(run.status(by="task").report)
    with pytest.raises(ArtifactError, match="supports task, instance, or candidate"):
        run.status(by="strategy")


def test_lifecycle_sessions_count_provider_calls_made_in_that_session(tmp_path: Path) -> None:
    run = plan(_definition(request_count=3), output=tmp_path / "lifecycle")
    run.execute()
    run.execute()

    sessions = load_json(run.root / "adaptive-lifecycle.json")["sessions"]
    assert [(row["providerInvocations"], row["replayedExecutions"]) for row in sessions] == [(3, 0), (0, 0)]


def test_interrupted_run_resumes_to_the_same_records_as_an_uninterrupted_run(tmp_path: Path, monkeypatch) -> None:
    definition = _definition(request_count=4, policy={"ref": "round_robin"})
    uninterrupted = plan(definition, output=tmp_path / "straight")
    uninterrupted.execute()

    resumed = plan(definition, output=tmp_path / "resumed")
    real_execute = TrialExecutionService.execute
    calls = {"count": 0}

    def interrupt_on_third_request(self, request, session, invoke, **kwargs):
        calls["count"] += 1
        if calls["count"] == 3:
            raise RuntimeError("simulated interruption after decision persistence")
        return real_execute(self, request, session, invoke, **kwargs)

    monkeypatch.setattr(TrialExecutionService, "execute", interrupt_on_third_request)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        resumed.execute()
    monkeypatch.setattr(TrialExecutionService, "execute", real_execute)
    assert [row["state"] for row in resumed.requests()] == ["delivered", "delivered", "started", "pending"]
    assert resumed.execute().counts == {"delivered": 4, "failed": 0, "started": 0}

    def comparable(run) -> list[dict]:
        rows = []
        for record in run.requests():
            row = json.loads(json.dumps(record))
            for key in ("requestDurationMs", "interrupted"):
                row.pop(key)
            row["attempts"][0]["decision"].pop("createdAt")
            rows.append(row)
        return rows

    assert comparable(resumed) == comparable(uninterrupted)
    assert [row["interrupted"] for row in resumed.requests()] == [False, False, True, False]
    assert verify_replay(resumed.root) == []
