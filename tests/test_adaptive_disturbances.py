"""WP-E: disturbances are scoped, seeded, recorded and refused when they could never apply."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxbench.ai.engine import Engine
from ctxbench.ai.failures import failure_category
from ctxbench.ai.models.base import AIRequest, ModelAdapter, ModelResponse, ToolCall, ToolResult, ToolSpec
from ctxbench.api import DefinitionError, plan
from ctxbench.execution.service import TrialExecutionService
from ctxbench.runtime.disturbances import build_runtime_disturbances
from ctxbench.util.fs import load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/adaptive/minimal.json"
DATASET = ROOT / "tests/fixtures/fake_dataset/dataset"


def _definition(*, request_count: int, disturbances: list[dict], policy: dict | None = None) -> dict:
    definition = json.loads(FIXTURE.read_text(encoding="utf-8"))
    definition["dataset"]["root"] = str(DATASET.resolve())
    definition["candidates"] = {
        "A": {"model": "mock", "configuration": "inline-json"},
        "B": {"model": "mock", "configuration": "inline-json"},
    }
    definition["workload"]["requests"] = [
        {"requestId": f"r-{i:04}", "taskId": "task_role", "instanceId": "person-001"}
        for i in range(1, request_count + 1)
    ]
    definition["policy"] = policy or {"ref": "round_robin", "params": {}}
    definition["disturbances"] = disturbances
    return definition


def _disturbance(**overrides) -> dict:
    return {"name": "outage", "version": "1", "component": "model", "kind": "failure",
            "failureRate": 0.5, "firstSequence": 1, "seed": 7, **overrides}


class _Model:
    def generate(self, *args, **kwargs):
        return "ok"


class _ToolRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_tools(self):
        return [ToolSpec(name="lookup", input_schema={"type": "object"})]

    def call_tool(self, name, arguments):
        self.calls.append(name)
        return ToolResult(name=name, content={"value": 1})

    def close(self) -> None:
        return None


def _model_draws(definition: dict, *, sequence: int, calls: int = 64) -> list[bool]:
    interceptors, _ = build_runtime_disturbances([definition], component_sequence=sequence,
                                                 candidate_id="A", sleeper=lambda _seconds: None)
    wrapper = interceptors["model"](_Model())
    failed = []
    for _ in range(calls):
        try:
            wrapper.generate(None, None)
            failed.append(False)
        except RuntimeError:
            failed.append(True)
    return failed


# --- plan-time validation ---------------------------------------------------------------------

@pytest.mark.parametrize("disturbances,message", [
    ([_disturbance(), _disturbance(seed=8)], "Duplicate disturbance name: outage"),
    ([_disturbance(component="remote_mcp")], "which no candidate uses"),
    ([_disturbance(component="local_function", candidates=["A"])], "candidate.*A do not use"),
    ([_disturbance(firstSequence=4)], "starts at sequence 4, after the last request .3."),
    ([_disturbance(candidates=["missing"])], "Unknown candidate.*disturbance"),
    ([{"name": "slow", "version": "1", "component": "model", "kind": "delay", "delayMs": 2.5}],
     "Invalid adaptive definition"),
])
def test_plan_refuses_a_disturbance_that_is_ambiguous_or_can_never_apply(tmp_path: Path, disturbances, message):
    with pytest.raises(DefinitionError, match=message):
        plan(_definition(request_count=3, disturbances=disturbances), output=tmp_path / "refused")


def test_plan_accepts_a_disturbance_reaching_the_last_request(tmp_path: Path):
    run = plan(_definition(request_count=3, disturbances=[_disturbance(firstSequence=3, candidates=["B"])]),
               output=tmp_path / "accepted")
    assert load_json(run.root / "adaptive-plan.json")["disturbances"][0]["firstSequence"] == 3


# --- seeded draws -----------------------------------------------------------------------------

def test_failure_draws_are_reproducible_and_independent_across_seed_sequence_and_name():
    base = _model_draws(_disturbance(seed=1), sequence=2)
    assert base == _model_draws(_disturbance(seed=1), sequence=2)
    assert True in base and False in base
    # seed + sequence is equal in both cases; the draws must still differ.
    assert base != _model_draws(_disturbance(seed=2), sequence=1)
    assert base != _model_draws(_disturbance(seed=1), sequence=3)
    assert base != _model_draws(_disturbance(seed=1, name="other"), sequence=2)


def test_stacked_disturbances_on_one_component_fail_independently_and_report_separately():
    definitions = [_disturbance(name="first", seed=3), _disturbance(name="second", seed=3)]
    interceptors, effects = build_runtime_disturbances(definitions, component_sequence=1, candidate_id="A")
    wrapper = interceptors["model"](_Model())
    outcomes = []
    for _ in range(64):
        try:
            wrapper.generate(None, None)
            outcomes.append(None)
        except RuntimeError as exc:
            outcomes.append(str(exc))
    rows = {row["name"]: row["injectedFailures"] for row in effects()}
    assert set(rows) == {"first", "second"}
    assert rows["first"] > 0 and rows["second"] > 0
    assert rows["first"] + rows["second"] == sum(outcome is not None for outcome in outcomes)


# --- scoping ----------------------------------------------------------------------------------

@pytest.mark.parametrize("sequence,candidate", [(1, "A"), (5, "A"), (3, "B")])
def test_no_interceptor_outside_the_declared_sequence_range_or_candidates(sequence: int, candidate: str):
    definition = _disturbance(firstSequence=2, lastSequence=4, candidates=["A"])
    interceptors, effects = build_runtime_disturbances([definition], component_sequence=sequence,
                                                       candidate_id=candidate)
    assert interceptors == {}
    assert effects() == []


@pytest.mark.parametrize("sequence", [2, 3, 4])
def test_interceptor_inside_the_declared_range_targets_only_its_component(sequence: int):
    definition = _disturbance(firstSequence=2, lastSequence=4, candidates=["A"])
    interceptors, _ = build_runtime_disturbances([definition], component_sequence=sequence, candidate_id="A")
    assert set(interceptors) == {"model"}


# --- tool components --------------------------------------------------------------------------

@pytest.mark.parametrize("component", ["local_function", "local_mcp", "remote_mcp"])
def test_tool_disturbance_counts_delay_and_tags_injected_failures(component: str):
    waits: list[float] = []
    delay = {"name": "slow-tools", "version": "2", "component": component, "kind": "delay",
             "delayMs": 40, "firstSequence": 1, "seed": 1}
    interceptors, effects = build_runtime_disturbances([delay], component_sequence=1, candidate_id="A",
                                                       sleeper=waits.append)
    assert set(interceptors) == {component}
    runtime = _ToolRuntime()
    wrapped = interceptors[component](runtime)
    wrapped.call_tool("lookup", {})
    wrapped.call_tool("lookup", {})
    assert waits == [0.04, 0.04] and runtime.calls == ["lookup", "lookup"]
    assert effects() == [{"name": "slow-tools", "version": "2", "appliedDelayMs": 80, "injectedFailures": 0}]

    outage = {"name": "tool-outage", "version": "1", "component": component, "kind": "failure",
              "failureRate": 1, "firstSequence": 1, "seed": 1}
    interceptors, effects = build_runtime_disturbances([outage], component_sequence=1, candidate_id="A")
    runtime = _ToolRuntime()
    with pytest.raises(RuntimeError, match="Injected disturbance tool-outage") as raised:
        interceptors[component](runtime).call_tool("lookup", {})
    assert failure_category(raised.value) == "injected_disturbance"
    assert runtime.calls == []  # the tool itself was not reached
    assert effects() == [{"name": "tool-outage", "version": "1", "appliedDelayMs": 0, "injectedFailures": 1}]


def test_injected_tool_failure_reaches_the_trace_as_injected_disturbance_not_tool_error():
    outage = {"name": "tool-outage", "version": "1", "component": "local_function", "kind": "failure",
              "failureRate": 1, "firstSequence": 1, "seed": 1}
    interceptors, effects = build_runtime_disturbances([outage], component_sequence=1, candidate_id="A")

    class ToolCallingModel(ModelAdapter):
        def generate(self, model_input, request, trace=None):
            return ModelResponse(requested_tool_calls=[ToolCall(name="lookup", arguments={})],
                                 duration_ms=1, input_tokens=1, output_tokens=0, total_tokens=1)

    engine = Engine(tool_runtime_factories={
        "local_function": lambda: interceptors["local_function"](_ToolRuntime())})
    engine._models["scripted"] = ToolCallingModel()
    result = engine.execute(AIRequest(**{
        "quest" + "ion": "task", "context": "", "provider_name": "scripted", "model_name": "scripted",
        "strategy_name": "local_function", "context_representation": "json", "params": {},
        "metadata": {"instance_id": "instance-1"},
    }))
    error = next(event for event in result.trace["events"] if event["type"] == "error")
    assert error["metadata"]["category"] == "injected_disturbance"
    assert effects()[0]["injectedFailures"] == 1


# --- whole runs -------------------------------------------------------------------------------

def _attempts(root: Path, request_count: int) -> list[dict]:
    return [load_json(root / "adaptive-records" / f"r-{i:04}.json")["attempts"][0]
            for i in range(1, request_count + 1)]


def test_two_runs_with_equal_seed_inject_identical_effects_only_where_declared(tmp_path: Path):
    disturbance = _disturbance(firstSequence=3, lastSequence=10, candidates=["A"])
    definition = _definition(request_count=12, disturbances=[disturbance])
    runs = []
    for name in ("first", "second"):
        run = plan(json.loads(json.dumps(definition)), output=tmp_path / name)
        run.execute()
        runs.append(_attempts(run.root, 12))
    first, second = runs

    def view(attempts):
        return [(row["decision"]["candidateId"], row["observation"]["status"],
                 row["observation"]["failureCategory"], row["disturbances"]) for row in attempts]

    assert view(first) == view(second)
    injected = 0
    for sequence, attempt in enumerate(first, start=1):
        in_scope = 3 <= sequence <= 10 and attempt["decision"]["candidateId"] == "A"
        if not in_scope:
            assert attempt["disturbances"] == []
            assert attempt["observation"]["status"] == "success"
            continue
        assert [row["name"] for row in attempt["disturbances"]] == ["outage"]
        failures = attempt["disturbances"][0]["injectedFailures"]
        assert failures in (0, 1)
        assert (attempt["observation"]["failureCategory"] == "injected_disturbance") == (failures == 1)
        injected += failures
    assert sum(1 for row in first if row["disturbances"]) == 4  # A at sequences 3, 5, 7, 9
    assert 0 < injected < 4  # with this seed the rate of 0.5 yields both outcomes

    other = plan(_definition(request_count=12, disturbances=[{**disturbance, "seed": 8}]),
                 output=tmp_path / "other-seed")
    other.execute()
    assert view(_attempts(other.root, 12)) != view(first)


def test_resume_keeps_recorded_disturbance_effects_without_executing_again(tmp_path: Path, monkeypatch):
    import ctxbench.adaptive.workflow as workflow_module

    definition = _definition(request_count=1, disturbances=[_disturbance(failureRate=1)],
                             policy={"ref": "static", "params": {"candidate": "A"}})
    run = plan(definition, output=tmp_path / "interrupted")
    real_write_json = workflow_module.write_json

    def interrupt_before_terminal_record(path, value):
        if Path(path).parent.name == "adaptive-records" and value.get("state") == "failed":
            raise RuntimeError("simulated interruption between durable writes")
        return real_write_json(path, value)

    monkeypatch.setattr(workflow_module, "write_json", interrupt_before_terminal_record)
    with pytest.raises(RuntimeError, match="between durable writes"):
        run.execute()
    saved = TrialExecutionService(run.root).attempts("r-0001")
    assert len(saved) == 1
    recorded = saved[0]["result"]["_adaptiveSignals"]["disturbances"]
    assert recorded == [{"name": "outage", "version": "1", "appliedDelayMs": 0, "injectedFailures": 1}]
    assert "_runtimeDisturbances" not in saved[0]["result"]

    monkeypatch.setattr(workflow_module, "write_json", real_write_json)
    assert run.execute().counts["failed"] == 1
    attempt = _attempts(run.root, 1)[0]
    assert attempt["disturbances"] == recorded
    assert attempt["observation"]["failureCategory"] == "injected_disturbance"
    assert len(TrialExecutionService(run.root).attempts("r-0001")) == 1
