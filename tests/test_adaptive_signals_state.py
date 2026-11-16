from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import pytest

from ctxbench.adaptive.plan import WindowSpec
from ctxbench.adaptive.policies.min_signal import MinSignalPolicy
from ctxbench.adaptive.policies.window_threshold import WindowThresholdPolicy
from ctxbench.adaptive.policy import CandidateRef, PolicyContractError
from ctxbench.adaptive.signals import SignalValue, classify_failure, extract_signals
from ctxbench.adaptive.state import Observation, ObservationLog, WindowSystemState
from ctxbench.api import DefinitionError, plan
from ctxbench.ai.models.claude import ClaudeModel
from ctxbench.ai.models.gemini import GeminiModel
from ctxbench.ai.models.mock import MockModel
from ctxbench.ai.models.openai import OpenAIModel
from ctxbench.ai.rate_control import classify_provider_error
from ctxbench.core.provenance import Provenance
from ctxbench.util.fs import load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/adaptive/minimal.json"
DATASET = ROOT / "tests/fixtures/fake_dataset/dataset"


def _signal(value: float | None, provenance: Provenance = Provenance.REPORTED, unit: str = "tokens"):
    return SignalValue(value, provenance if value is not None else Provenance.UNAVAILABLE, unit)


def _observation(index: int, candidate: str, value: float | None, *, status: str = "success",
                 category: str | None = None, provenance: Provenance = Provenance.REPORTED) -> Observation:
    return Observation(index, candidate, status, category,
                       {"total_tokens": _signal(value, provenance),
                        "latency_ms": _signal(float(index), Provenance.MEASURED, "ms")})


def _state(observations=(), *, decision_index=None, window=WindowSpec(3), signals=()):
    prefix = tuple(observations)
    return WindowSystemState(
        decision_index=decision_index or len(prefix) + 1, observations=prefix, memo=None,
        seed=13, decision_id=f"r-{len(prefix) + 1}:d1", default_window=window,
        candidate_ids=("A", "B", "C"), declared_signals=signals,
    )


def test_signal_extraction_preserves_values_provenance_and_missing_usage():
    result = {
        "status": "error", "response": "", "errorMessage": "failed",
        "timing": {"durationMs": 12},
        "usage": {"inputTokens": 7, "outputTokens": 2},
        "metricsSummary": {"totalTokens": None, "knownTotalTokens": 9,
                            "totalTokensProvenance": "unavailable", "cachedInputTokens": 3,
                            "reasoningTokens": None, "modelCalls": 1, "toolCalls": 2},
        "trace": {"events": [{"type": "error", "name": "error",
                               "metadata": {"category": "context_overflow"}}]},
    }
    signals, known_subtotals, category = extract_signals(result, accepted=False)
    assert category == "context_overflow"
    assert signals["latency_ms"].value == 12
    assert signals["latency_ms"].provenance == Provenance.MEASURED
    assert signals["input_tokens"].value == 7
    assert signals["input_tokens"].provenance == Provenance.REPORTED
    assert signals["total_tokens"].value is None
    assert known_subtotals == {"total_tokens": 9}
    assert set(signals["total_tokens"].to_dict()) == {"value", "provenance", "unit"}
    assert signals["total_tokens"].provenance == Provenance.UNAVAILABLE
    assert signals["reasoning_tokens"].value is None
    assert signals["failed"].value == 1
    assert signals["accepted"].value == 0
    estimated, no_subtotals, _ = extract_signals({
        "status": "success", "usage": {"inputTokens": 4, "outputTokens": 2},
        "metricsSummary": {"totalTokens": 6, "totalTokensProvenance": "estimated"},
    }, accepted=True)
    assert estimated["input_tokens"].provenance == Provenance.ESTIMATED
    assert no_subtotals == {}


@pytest.mark.parametrize("adapter_class,error", [
    (OpenAIModel, "context_length_exceeded: request too large"),
    (ClaudeModel, "prompt is too long for this model"),
    (GeminiModel, "input token count exceeds the maximum number of tokens"),
    (MockModel, "Mock context token limit exceeded"),
])
def test_each_adapter_recognises_its_own_context_overflow(adapter_class, error: str):
    adapter = adapter_class()
    assert adapter.failure_category(RuntimeError(error)) == "context_overflow"
    assert adapter.failure_category(RuntimeError("opaque failure")) is None
    info = classify_provider_error("any", RuntimeError(error), adapter=adapter)
    assert (info.kind, info.category) == ("fatal", "context_overflow")


def test_context_overflow_is_recognised_only_by_the_adapter_that_owns_the_wording():
    gemini_wording = RuntimeError("input token count exceeds the maximum number of tokens")
    assert MockModel().failure_category(gemini_wording) is None
    # Without the adapter the classifier cannot tell an overflow from any provider error.
    assert classify_provider_error("google", gemini_wording).category == "provider_error"

    class CodedError(RuntimeError):
        code = "context_length_exceeded"

    assert OpenAIModel().failure_category(CodedError("request rejected")) == "context_overflow"


def test_provider_errors_normalize_rate_limit_and_fallback_categories():
    assert classify_provider_error("openai", RuntimeError("429 rate limit exceeded")).category == "rate_limited"
    assert classify_provider_error("openai", RuntimeError("opaque failure")).category == "provider_error"


def test_failure_classifier_maps_engine_conditions_and_empty_answers():
    assert classify_failure({
        "status": "error", "trace": {"events": [{"type": "error", "name": "error",
            "metadata": {"exceptionType": "CapabilityUnavailableError", "category": "provider_error"}}]},
    }) == "capability_unavailable"
    assert classify_failure({"status": "error", "response": "",
                             "errorMessage": "Model returned empty answer"}) == "empty_response"
    assert classify_failure({"status": "error", "response": "", "errorMessage": "failure"}) == "unknown"


def test_state_statistics_cover_empty_missing_provenance_capacity_and_percentile():
    empty = _state()
    assert empty.window("total_tokens", "sum").value == 0
    assert empty.window("total_tokens", "sum").provenance == Provenance.DERIVED
    assert empty.window("total_tokens", "count").value == 0
    assert empty.window("total_tokens", "mean").value is None

    state = _state([
        _observation(1, "A", 10, provenance=Provenance.ESTIMATED),
        _observation(2, "B", None, status="error", category="context_overflow"),
        _observation(3, "A", 30),
    ], decision_index=4)
    total = state.window("total_tokens", "sum", capacity=20)
    assert total.value is None and total.known_subtotal == 40
    assert total.missing_count == 1 and total.sample_count == 2
    partial_mean = state.window("total_tokens", "mean", capacity=20)
    assert partial_mean.value == 20
    assert partial_mean.provenance == Provenance.ESTIMATED
    assert partial_mean.remaining == 0
    assert partial_mean.utilisation == 1
    assert state.window("total_tokens", "median").value == 20
    assert state.window("total_tokens", "min").value == 10
    assert state.window("total_tokens", "max").value == 30
    assert state.window("total_tokens", "last").value == 30
    assert state.window("total_tokens", "p50").value == 20
    assert state.window("failed.context_overflow", "rate").value == pytest.approx(1 / 3)
    assert state.window("latency_ms", "count").value == 3
    assert len(state.reading_audit) == 9


def test_state_windows_candidate_scope_fixed_reset_and_unknown_signals():
    observations = [_observation(1, "A", 3), _observation(2, "B", 8),
                    _observation(3, "A", 5), _observation(4, "B", 2)]
    fixed = _state(observations[:2], decision_index=3, window=WindowSpec(2, "fixed"))
    assert fixed.window("total_tokens", "sum").value == 0
    assert fixed.window("total_tokens", "sum", window={"all": True}).value == 11
    assert fixed.window("total_tokens", "sum", scope="candidate:A", window={"all": True}).value == 3
    assert fixed.candidate("A").observation_count == 1
    with pytest.raises(PolicyContractError, match="Unknown signal"):
        fixed.window("request_context_size", "mean")
    with pytest.raises(PolicyContractError, match="Unknown signal"):
        fixed.window("failed.not_a_category", "rate")
    with pytest.raises(PolicyContractError, match="Invalid candidate scope"):
        fixed.window("total_tokens", "sum", scope="candidate:missing")


def test_observation_log_rejects_noncausal_order():
    log = ObservationLog([_observation(2, "A", 1)])
    with pytest.raises(ValueError, match="strictly increasing"):
        log.append(_observation(1, "A", 1))


def test_window_threshold_handles_boundaries_unavailable_and_capacity():
    policy = WindowThresholdPolicy(
        signal="total_tokens", statistic="sum", tiers=[{"upTo": 0.5, "select": "A"}],
        otherwise="B", when_unavailable="C", capacity=10,
    )
    candidates = tuple(CandidateRef(name, {}) for name in ("A", "B", "C"))
    assert policy.decide(candidates, _state()).candidate_id == "A"  # empty sum is observed zero
    at_boundary = _state([_observation(1, "A", 5)], decision_index=2)
    assert policy.decide(candidates, at_boundary).candidate_id == "A"
    over_boundary = _state([_observation(1, "A", 6)], decision_index=2)
    assert policy.decide(candidates, over_boundary).candidate_id == "B"
    unknown_sum = _state([_observation(1, "A", None, status="error")], decision_index=2)
    assert policy.decide(candidates, unknown_sum).candidate_id == "C"
    assert "utilisation=0.5" in policy.decide(candidates, at_boundary).reason


def test_window_threshold_warmup_and_invalid_policy_parameters():
    candidates = tuple(CandidateRef(name, {}) for name in ("A", "B", "C"))
    policy = WindowThresholdPolicy(
        signal="latency_ms", statistic="mean", tiers=[{"upTo": 10, "select": "A"}],
        otherwise="B", when_unavailable="C", min_samples=2,
    )
    assert policy.decide(candidates, _state([_observation(1, "A", 4)], decision_index=2)).candidate_id == "C"
    with pytest.raises(ValueError, match="strictly ascending"):
        WindowThresholdPolicy(signal="total_tokens", statistic="sum",
                              tiers=[{"upTo": 2, "select": "A"}, {"upTo": 1, "select": "B"}],
                              otherwise="A", when_unavailable="B")
    with pytest.raises(ValueError, match="fractions"):
        WindowThresholdPolicy(signal="total_tokens", statistic="sum",
                              tiers=[{"upTo": 2, "select": "A"}], otherwise="A",
                              when_unavailable="B", capacity=10)


def test_window_threshold_unknown_candidate_is_rejected_during_planning(tmp_path: Path):
    definition = _definition(request_count=1, policy={"ref": "window_threshold", "params": {
        "signal": "total_tokens", "statistic": "sum", "tiers": [{"upTo": 5, "select": "missing"}],
        "otherwise": "B", "when_unavailable": "C",
    }})
    with pytest.raises(DefinitionError, match="unknown candidates: missing"):
        plan(definition, output=tmp_path / "invalid-target")


def test_min_signal_explores_in_order_then_uses_declared_order_for_ties():
    candidates = (CandidateRef("B", {}), CandidateRef("A", {}))
    policy = MinSignalPolicy(signal="total_tokens", statistic="mean", min_samples=1)
    state = _state([_observation(1, "B", 5)], decision_index=2)
    assert policy.decide(candidates, state).candidate_id == "A"
    tied = _state([_observation(1, "B", 5), _observation(2, "A", 5)], decision_index=3)
    assert policy.decide(candidates, tied).candidate_id == "B"
    left_window = _state([_observation(1, "B", 5), _observation(2, "A", 5)],
                         decision_index=3, window=WindowSpec(1))
    assert policy.decide(candidates, left_window).candidate_id == "B"


def _definition(*, request_count: int, policy: dict) -> dict:
    definition = json.loads(FIXTURE.read_text(encoding="utf-8"))
    definition["dataset"]["root"] = str(DATASET.resolve())
    definition["candidates"] = {
        "A": {"model": "mock", "configuration": "inline-json"},
        "B": {"model": "mock", "configuration": "inline-json"},
        "C": {"model": "mock", "configuration": "inline-json"},
    }
    definition["workload"]["requests"] = [
        {"requestId": f"r-{i:04}", "taskId": "task_role", "instanceId": "person-001"}
        for i in range(1, request_count + 1)
    ]
    definition["policy"] = policy
    return definition


def test_window_threshold_workflow_records_readings_and_fixed_window_switches(tmp_path: Path, monkeypatch):
    import ctxbench.adaptive.workflow as workflow_module

    definition = _definition(request_count=4, policy={"ref": "window_threshold", "params": {
        "signal": "total_tokens", "statistic": "sum", "window": {"requests": 2, "mode": "fixed"},
        "capacity": 10, "tiers": [{"upTo": 0.5, "select": "A"}],
        "otherwise": "B", "when_unavailable": "C",
    }})
    run = plan(definition, output=tmp_path / "fixed-window")

    def scripted(_execution_request, _session, *, dataset, trace_options, runtime_interceptors=None):
        del dataset, trace_options
        count = int(_execution_request.correlation_id.rsplit("-", 1)[-1])
        tokens = 6 if count % 2 else 1
        return {"status": "success", "response": "ok", "errorMessage": None,
                "timing": {"durationMs": 1}, "usage": {"inputTokens": tokens, "outputTokens": 0},
                "metricsSummary": {"totalTokens": tokens, "totalTokensProvenance": "reported",
                                   "knownTotalTokens": tokens, "usageCompleteness": "complete",
                                   "cachedInputTokens": None, "reasoningTokens": None,
                                   "modelCalls": 1, "toolCalls": 0}, "trace": {"events": []}}

    import ctxbench.adaptive.runtime_adapter as runtime_adapter
    monkeypatch.setattr(runtime_adapter, "invoke_adaptive_execution", scripted)
    run.execute()
    records = [load_json(run.root / "adaptive-records" / f"r-{i:04}.json") for i in range(1, 5)]
    chosen = [row["attempts"][0]["decision"]["candidateId"] for row in records]
    assert chosen == ["A", "B", "A", "B"]  # fixed block resets; 6 / 10 is above the tier
    for row in records:
        assert row["attempts"][0]["decision"]["readings"]
        assert row["attempts"][0]["observation"]["signals"]["total_tokens"]["provenance"] == "reported"
    from ctxbench.adaptive.testing import verify_replay
    assert verify_replay(run.root) == []


def test_context_overflow_failure_becomes_a_policy_signal_without_fallback(tmp_path: Path):
    definition = _definition(request_count=2, policy={"ref": "window_threshold", "params": {
        "signal": "failed.context_overflow", "statistic": "mean",
        "tiers": [{"upTo": 0.5, "select": "A"}], "otherwise": "B", "when_unavailable": "A",
    }})
    definition["models"]["mock"]["modelParams"]["context_limit_tokens"] = 1
    run = plan(definition, output=tmp_path / "context-overflow")
    assert run.execute().counts["failed"] == 2

    first = load_json(run.root / "adaptive-records" / "r-0001.json")
    second = load_json(run.root / "adaptive-records" / "r-0002.json")
    assert first["state"] == second["state"] == "failed"
    assert first["attempts"][0]["observation"]["failureCategory"] == "context_overflow"
    assert first["attempts"][0]["observation"]["signals"]["latency_ms"]["provenance"] == "measured"
    assert first["attempts"][0]["observation"]["signals"]["total_tokens"]["value"] is None
    assert first["attempts"][0]["observation"]["signals"]["total_tokens"]["provenance"] == "unavailable"
    assert first["attempts"][0]["decision"]["candidateId"] == "A"
    second_decision = second["attempts"][0]["decision"]
    assert second_decision["candidateId"] == "B"
    reading = second_decision["readings"][0]
    assert reading["value"] == 1
    assert set(reading) == {"signal", "statistic", "scope", "window", "capacity", "value",
                            "provenance", "sampleCount", "missingCount", "knownSubtotal"}
    assert first["attempts"][0]["observation"]["knownSubtotals"] == {}
    assert len(first["attempts"]) == len(second["attempts"]) == 1


def test_resume_rebuilds_window_readings_without_reexecuting_terminal_requests(
    tmp_path: Path, monkeypatch,
):
    import ctxbench.adaptive.runtime_adapter as runtime_adapter
    from ctxbench.execution.service import TrialExecutionService

    definition = _definition(request_count=4, policy={"ref": "window_threshold", "params": {
        "signal": "total_tokens", "statistic": "sum", "window": {"requests": 2},
        "tiers": [{"upTo": 5, "select": "A"}], "otherwise": "B", "when_unavailable": "B",
    }})

    def scripted(execution_request, _session, *, dataset, trace_options, runtime_interceptors=None):
        del dataset, trace_options
        index = int(execution_request.correlation_id.rsplit("-", 1)[-1])
        tokens = {1: 2, 2: 8, 3: 3, 4: 1}[index]
        return {"status": "success", "response": "ok", "errorMessage": None,
                "timing": {"durationMs": index}, "usage": {"inputTokens": tokens, "outputTokens": 0},
                "metricsSummary": {"totalTokens": tokens, "totalTokensProvenance": "reported",
                                   "knownTotalTokens": tokens, "usageCompleteness": "complete",
                                   "modelCalls": 1, "toolCalls": 0}, "trace": {"events": []}}

    monkeypatch.setattr(runtime_adapter, "invoke_adaptive_execution", scripted)
    uninterrupted = plan(definition, output=tmp_path / "uninterrupted")
    uninterrupted.execute()
    expected = [load_json(uninterrupted.root / "adaptive-records" / f"r-{i:04}.json")
                for i in range(1, 5)]

    resumed = plan(definition, output=tmp_path / "resumed")
    real_execute = TrialExecutionService.execute
    calls: list[str] = []

    def interrupt_on_second(self, request, session, invoke, **kwargs):
        calls.append(request.correlation_id)
        if request.correlation_id == "r-0002":
            raise RuntimeError("stop after persisting second decision")
        return real_execute(self, request, session, invoke, **kwargs)

    monkeypatch.setattr(TrialExecutionService, "execute", interrupt_on_second)
    with pytest.raises(RuntimeError, match="persisting second decision"):
        resumed.execute()
    first_before = load_json(resumed.root / "adaptive-records" / "r-0001.json")
    second_before = load_json(resumed.root / "adaptive-records" / "r-0002.json")
    assert second_before["state"] == "started"
    assert len(second_before["attempts"]) == 1

    monkeypatch.setattr(TrialExecutionService, "execute", real_execute)
    resumed.execute()
    actual = [load_json(resumed.root / "adaptive-records" / f"r-{i:04}.json")
              for i in range(1, 5)]
    for expected_row, actual_row in zip(expected, actual, strict=True):
        expected_decision = expected_row["attempts"][0]["decision"]
        actual_decision = actual_row["attempts"][0]["decision"]
        assert (actual_decision["candidateId"], actual_decision["readings"]) == (
            expected_decision["candidateId"], expected_decision["readings"]
        )
        assert actual_row["attempts"][0]["observation"]["signals"] == \
            expected_row["attempts"][0]["observation"]["signals"]
    assert calls == ["r-0001", "r-0002"]
    assert first_before["attempts"][0]["decision"]["readings"] == \
        actual[0]["attempts"][0]["decision"]["readings"]


def test_resume_copies_signals_from_completed_execution_record(tmp_path: Path, monkeypatch):
    import ctxbench.adaptive.runtime_adapter as runtime_adapter
    import ctxbench.adaptive.workflow as workflow_module

    run = plan(_definition(request_count=1, policy={"ref": "static", "params": {"candidate": "A"}}),
               output=tmp_path / "between-writes")
    invoke_calls = []

    def scripted(execution_request, _session, *, dataset, trace_options, runtime_interceptors=None):
        del dataset, trace_options
        invoke_calls.append(execution_request.correlation_id)
        return {"status": "success", "response": "ok", "errorMessage": None,
                "timing": {"durationMs": 7}, "usage": {"inputTokens": 3, "outputTokens": 1},
                "metricsSummary": {"totalTokens": 4, "totalTokensProvenance": "reported",
                                   "knownTotalTokens": 4, "usageCompleteness": "complete",
                                   "modelCalls": 1, "toolCalls": 0}, "trace": {"events": []}}

    monkeypatch.setattr(runtime_adapter, "invoke_adaptive_execution", scripted)
    real_write_json = workflow_module.write_json

    def interrupt_after_execution(path, value):
        path = Path(path)
        if path.parent.name == "adaptive-records" and value.get("state") == "delivered":
            raise RuntimeError("simulated interruption between durable writes")
        return real_write_json(path, value)

    monkeypatch.setattr(workflow_module, "write_json", interrupt_after_execution)
    with pytest.raises(RuntimeError, match="between durable writes"):
        run.execute()
    execution_record = next((run.root / "execution-records").glob("*/*.json"))
    saved_execution = load_json(execution_record)
    assert saved_execution["result"]["_adaptiveSignals"]["signals"]["total_tokens"]["value"] == 4
    assert invoke_calls == ["r-0001"]

    monkeypatch.setattr(workflow_module, "write_json", real_write_json)
    assert run.execute().counts["delivered"] == 1
    record = load_json(run.root / "adaptive-records" / "r-0001.json")
    assert record["attempts"][0]["observation"]["signals"] == \
        saved_execution["result"]["_adaptiveSignals"]["signals"]
    assert invoke_calls == ["r-0001"]


@pytest.mark.parametrize("adapter_class,message", [
    (OpenAIModel, "This model's maximum context length is 128000 tokens. "
                  "However, your messages resulted in 142933 tokens."),
    (MockModel, "Mock context token limit exceeded: 1429 > 5"),
])
def test_context_overflow_with_429_digits_in_a_token_count_is_not_a_rate_limit(adapter_class, message: str):
    info = classify_provider_error("any", RuntimeError(message), adapter=adapter_class())
    assert info.category == "context_overflow"
    assert info.kind == "fatal"  # never retried


def test_rate_limit_detection_needs_a_standalone_429_or_a_429_status():
    digits_only = classify_provider_error("openai", RuntimeError("lookup failed: section 4290 not found"))
    assert (digits_only.kind, digits_only.category) == ("fatal", "provider_error")
    standalone = classify_provider_error("openai", RuntimeError("Error code: 429 - slow down"))
    assert (standalone.kind, standalone.category) == ("rate_limit", "rate_limited")

    class StatusError(RuntimeError):
        status_code = 429

    by_status = classify_provider_error("openai", StatusError("maximum context length reached for quota"),
                                        adapter=OpenAIModel())
    assert (by_status.kind, by_status.category) == ("rate_limit", "rate_limited")


def test_signal_extraction_without_metrics_summary_leaves_call_counts_unavailable():
    signals, _, category = extract_signals({"status": "error", "response": "", "errorMessage": "boom"},
                                           accepted=False)
    assert category == "unknown"
    for name in ("model_calls", "tool_calls", "latency_ms", "total_tokens", "input_tokens"):
        assert signals[name].value is None
        assert signals[name].provenance == Provenance.UNAVAILABLE
    observed, _, _ = extract_signals({"status": "success", "metricsSummary": {"modelCalls": 0, "toolCalls": 0}},
                                     accepted=True)
    assert observed["model_calls"].value == 0
    assert observed["model_calls"].provenance == Provenance.MEASURED


def test_failure_classifier_reads_recorded_category_and_does_not_guess_from_text():
    assert classify_failure({"status": "error", "response": "", "failureCategory": "tool_error",
                             "errorMessage": "boom"}) == "tool_error"
    assert classify_failure({"status": "error", "response": "", "failureCategory": "provider_error",
                             "errorMessage": "Invalid tool_choice parameter"}) == "provider_error"
    # No recorded category: wording such as "tool" or "context length" is not evidence.
    assert classify_failure({"status": "error", "response": "",
                             "errorMessage": "Invalid tool_choice parameter"}) == "unknown"
    assert classify_failure({"status": "error", "response": "",
                             "errorMessage": "context length mismatch in tool output"}) == "unknown"
    # Only error events carry a category; a later non-error event is ignored.
    assert classify_failure({"status": "error", "trace": {"events": [
        {"type": "error", "name": "error", "metadata": {"category": "provider_error"}},
        {"type": "tool", "name": "call_tool", "metadata": {}},
    ]}}) == "provider_error"


def test_min_signal_does_not_lock_onto_a_candidate_whose_signal_is_never_available():
    candidates = (CandidateRef("A", {}), CandidateRef("B", {}))
    policy = MinSignalPolicy(signal="total_tokens", statistic="mean")
    failing = [_observation(1, "A", None, status="error", category="context_overflow")]
    # A was observed once without usage: it has been explored, so B is explored next.
    assert policy.decide(candidates, _state(failing, window=WindowSpec(10))).candidate_id == "B"
    with_b = failing + [_observation(2, "B", 7)]
    for extra in range(3):
        prefix = with_b + [_observation(3 + i, "B", 7) for i in range(extra)]
        decision = policy.decide(candidates, _state(prefix, window=WindowSpec(10)))
        assert decision.candidate_id == "B"
        assert "unavailable_candidates=1" in decision.reason
    # Once A's observation leaves the window it is explored again.
    left = with_b + [_observation(3, "B", 7)]
    assert policy.decide(candidates, _state(left, window=WindowSpec(2))).candidate_id == "A"


def test_min_signal_with_every_reading_unavailable_selects_the_least_observed_candidate():
    candidates = (CandidateRef("A", {}), CandidateRef("B", {}))
    policy = MinSignalPolicy(signal="total_tokens", statistic="mean")
    prefix = [_observation(1, "A", None), _observation(2, "B", None), _observation(3, "A", None)]
    decision = policy.decide(candidates, _state(prefix, window=WindowSpec(10)))
    assert decision.candidate_id == "B"
    assert "unavailable for every candidate" in decision.reason
    tie = prefix + [_observation(4, "B", None)]
    assert policy.decide(candidates, _state(tie, window=WindowSpec(10))).candidate_id == "A"


def test_min_signal_percentile_requires_two_samples():
    with pytest.raises(ValueError, match="min_samples >= 2"):
        MinSignalPolicy(signal="latency_ms", statistic="p95")
    MinSignalPolicy(signal="latency_ms", statistic="p95", min_samples=2)


def test_system_state_holds_no_request_identifier_in_any_attribute():
    request_id = "request-secret-0042"
    state = WindowSystemState(
        decision_index=2, observations=[_observation(1, "A", 5)], memo={"position": 1}, seed=5,
        decision_id=f"{request_id}:d1", default_window=WindowSpec(2), candidate_ids=("A", "B", "C"),
    )
    state.window("total_tokens", "sum")
    seen: set[int] = set()

    def strings(value):
        if id(value) in seen or isinstance(value, (int, float, bool, type(None))):
            return
        seen.add(id(value))
        if isinstance(value, str):
            yield value
        elif isinstance(value, Mapping):
            for key, item in value.items():
                yield from strings(key)
                yield from strings(item)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                yield from strings(item)
        else:
            names = [name for klass in type(value).__mro__ for name in getattr(klass, "__slots__", ())]
            names += list(getattr(value, "__dict__", {}))
            for name in names:
                if hasattr(value, name):
                    yield from strings(getattr(value, name))

    found = list(strings(state))
    assert "A" in found  # the walk reaches private attributes (the observation log)
    assert not any(request_id in value for value in found)
    assert not hasattr(state, "_decision_id") and not hasattr(state, "_seed")


def test_known_subtotal_is_kept_apart_from_the_signal_and_feeds_window_sums():
    partial = Observation(2, "A", "success", None, {"total_tokens": _signal(None)},
                          known_subtotals={"total_tokens": 4})
    state = _state([_observation(1, "A", 10), partial], window=WindowSpec(5))
    total = state.window("total_tokens", "sum")
    assert total.value is None and total.provenance == Provenance.UNAVAILABLE
    assert total.known_subtotal == 14
    assert state.window("total_tokens", "mean").value == 10  # a subtotal is never a sample

    record = {"sequenceIndex": 2, "attempts": [{
        "decision": {"candidateId": "A"},
        "observation": {"status": "success", "failureCategory": None,
                        "signals": {"total_tokens": _signal(None).to_dict()},
                        "knownSubtotals": {"total_tokens": 4}},
    }]}
    assert Observation.from_record(record) == partial


@pytest.mark.parametrize("params,message", [
    ({"signal": "request_context_size", "statistic": "mean"}, "Unknown signal"),
    ({"signal": "failed.not_a_category", "statistic": "rate"}, "Unknown signal"),
    ({"signal": "total_tokens", "statistic": "p1e1"}, "Unknown statistic"),
    ({"signal": "total_tokens", "statistic": "p100"}, "Unknown statistic"),
    ({"signal": "total_tokens", "statistic": "rate"}, "requires a 0/1 signal"),
])
def test_invalid_policy_reading_is_refused_at_planning_with_the_runtime_rule(tmp_path: Path, params, message):
    policy = {"ref": "window_threshold", "params": {
        **params, "tiers": [{"upTo": 1, "select": "A"}], "otherwise": "B", "when_unavailable": "A"}}
    with pytest.raises(DefinitionError, match=message):
        plan(_definition(request_count=1, policy=policy), output=tmp_path / "invalid-reading")
    # The same pair is refused when read at run time: one rule, one parser.
    with pytest.raises(PolicyContractError, match=message):
        _state().window(params["signal"], params["statistic"])


def test_planning_checks_readings_reported_by_any_policy_not_only_named_built_ins():
    from ctxbench.adaptive.workflow import _validate_policy_readings

    class ExternalPolicy:
        def signal_readings(self):
            return (("quality.accuracy", "mean"), ("latency_ms", "p95"))

    _validate_policy_readings(ExternalPolicy(), [{"id": "quality.accuracy"}])
    with pytest.raises(ValueError, match="Unknown signal 'quality.accuracy'"):
        _validate_policy_readings(ExternalPolicy(), [])
    _validate_policy_readings(object(), [])  # a policy that reports nothing is not checked
