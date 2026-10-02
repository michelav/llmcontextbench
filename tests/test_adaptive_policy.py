from __future__ import annotations

from copy import deepcopy

from ctxbench.adaptive import (
    AdaptivePolicy, Candidate, Decision, Estimate, EstimateKey, FixedPolicy, Observation,
    PerformanceEstimate, PolicyConfig, PolicyState, Provenance, RequestFeatures,
    RouterPolicy, SizeBin, TokenUsage, estimate_from_observations,
)


def est(value: float | None, provenance: Provenance = Provenance.ESTIMATED, n: int = 5) -> Estimate:
    return Estimate(value, provenance if value is not None else Provenance.UNAVAILABLE, n if value is not None else 0)


def setup(latencies: tuple[float | None, float | None] = (100, 180),
          tokens: tuple[float | None, float | None] = (1000, 500)) -> tuple[PolicyState, tuple[Candidate, ...]]:
    state = PolicyState("router", "1", calibration={
        EstimateKey("inline", SizeBin.SMALL): PerformanceEstimate(est(latencies[0]), est(tokens[0])),
        EstimateKey("local", SizeBin.SMALL): PerformanceEstimate(est(latencies[1]), est(tokens[1])),
    })
    return state, (Candidate("inline", True, True), Candidate("local", True, True))


def features(index: int = 1) -> RequestFeatures:
    return RequestFeatures.from_context_bytes(index, 1024)


def test_objective_routes_by_tokens_or_latency_and_handles_unserved() -> None:
    state, candidates = setup()
    policy = RouterPolicy(state, PolicyConfig(150), probes=False)
    assert policy.decide(features(), candidates).selected_configuration == "inline"
    missed, candidates = setup(latencies=(220, 180))
    decision = RouterPolicy(missed, PolicyConfig(150), probes=False).decide(features(), candidates)
    assert decision.selected_configuration == "local"
    assert decision.reason == "lowest_estimated_latency_objective_missed"
    empty = RouterPolicy(missed, PolicyConfig(150)).decide(features(), ())
    assert empty.selected_configuration is None


def test_ties_threshold_cooldown_and_ineligibility_override() -> None:
    state, candidates = setup(latencies=(100, 100), tokens=(100, 100))
    policy = RouterPolicy(state, PolicyConfig(200), probes=False)
    assert policy.decide(features(), candidates).selected_configuration == "inline"

    state.incumbent = "inline"
    state.calibration[EstimateKey("local", SizeBin.SMALL)] = PerformanceEstimate(est(100), est(91))
    d = policy.decide(features(2), candidates)
    assert d.selected_configuration == "inline"  # 9% improvement
    state.calibration[EstimateKey("local", SizeBin.SMALL)] = PerformanceEstimate(est(100), est(90))
    d = policy.decide(features(3), candidates)
    assert d.selected_configuration == "inline"  # cooldown after initial decision
    d = policy.decide(features(7), candidates)
    assert d.selected_configuration == "local"  # cooldown elapsed, exactly 10%
    state.last_switch_sequence = 7
    d = policy.decide(features(8), (Candidate("inline", True, False), candidates[1]))
    assert d.selected_configuration == "local"  # ineligibility overrides cooldown


def test_probe_schedule_and_fixed_arms() -> None:
    state, candidates = setup()
    policy = RouterPolicy(state, PolicyConfig(150))
    for idx in range(1, 61):
        before = deepcopy(state)
        decision = policy.decide(features(idx), candidates)
        if idx in {10, 20, 30, 40, 50, 60}:
            assert decision.probe and decision.reason == "scheduled_probe"
            normal = RouterPolicy(before, PolicyConfig(150), probes=False)
            assert decision.selected_configuration != normal.decide(features(idx), candidates).selected_configuration
    state, candidates = setup()
    fixed = FixedPolicy(state, "inline")
    assert fixed.decide(features(10), candidates).probe is False


def test_recent_means_require_three_valid_eval_observations_and_cap_at_five() -> None:
    state = PolicyState("adaptive", "1", calibration={
        EstimateKey("inline", SizeBin.SMALL): PerformanceEstimate(est(200), est(1000))
    })
    for i in range(1, 3):
        state.record(Observation("inline", SizeBin.SMALL, "success", i * 10,
                                 TokenUsage(100, Provenance.REPORTED), True), adaptive=True)
    assert state.estimates == {}
    state.record(Observation("inline", SizeBin.SMALL, "error", 5, TokenUsage(None, Provenance.UNAVAILABLE), True), adaptive=True)
    for duration in (30, 40, 50, 60, 70, 80):
        state.record(Observation("inline", SizeBin.SMALL, "success", duration,
                                 TokenUsage(None, Provenance.UNAVAILABLE), True), adaptive=True)
    updated = state.estimates[EstimateKey("inline", SizeBin.SMALL)]
    assert updated.latency_ms.value == 60  # last five: 40, 50, 60, 70, 80
    assert updated.latency_ms.observation_count == 5
    assert updated.total_tokens.value is None


def test_frozen_state_records_without_updating_and_runtime_only_updates_adaptive() -> None:
    for adaptive in (False, True):
        state, _ = setup()
        original = state.calibration[EstimateKey("inline", SizeBin.SMALL)]
        obs = Observation("inline", SizeBin.SMALL, "success", 10,
                          TokenUsage(90, Provenance.REPORTED), True)
        for _ in range(3):
            state.record(obs, adaptive=adaptive)
        assert len(state.recent_observations[EstimateKey("inline", SizeBin.SMALL)]) == 3
        assert state.calibration[EstimateKey("inline", SizeBin.SMALL)] == original
        assert (state.estimates.get(EstimateKey("inline", SizeBin.SMALL)) is not None) is adaptive
        state.record(Observation("local", SizeBin.SMALL, "success", 1,
                                 TokenUsage(1, Provenance.REPORTED), False), adaptive=True)
        assert EstimateKey("local", SizeBin.SMALL) not in state.estimates


def test_rolling_estimator_and_policy_contracts_expose_no_forbidden_fields() -> None:
    observations = [Observation("x", SizeBin.LARGE, "success", n,
                                TokenUsage(None, Provenance.UNAVAILABLE)) for n in range(1, 8)]
    result = estimate_from_observations(observations)
    assert result.latency_ms.value == 5
    assert result.total_tokens.value is None
    assert set(RequestFeatures.__dataclass_fields__) == {"sequence_index", "context_bytes", "size_bin"}
    assert "task_text" not in Decision.__dataclass_fields__
    assert "target_identity" not in Candidate.__dataclass_fields__
    assert "oracle" not in Observation.__dataclass_fields__
    assert "evaluation_result" not in Decision.__dataclass_fields__
    assert "phase" not in RequestFeatures.__dataclass_fields__
