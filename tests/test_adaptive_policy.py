from __future__ import annotations

import json
from dataclasses import fields

import pytest

from ctxbench.adaptive import (
    INLINE_CONFIGURATION as INLINE, LOCAL_MCP_CONFIGURATION as LOCAL, POLICY_VERSION,
    AdaptivePolicy, Candidate, ContextFit, Decision, DecisionRecord, DecisionSidecar,
    Estimate, EstimateKey, FixedPolicy, Observation, PerformanceEstimate, PolicyConfig,
    PolicyState, Provenance as P, RequestFeatures, RouterPolicy, RunMetadata, SizeBin,
    TokenUsage, estimate_from_observations,
)
from ctxbench.adapters.repoqa.workload import prepare_request_features


def est(value, provenance=P.ESTIMATED, n=5):
    return Estimate(value, provenance if value is not None else P.UNAVAILABLE, n if value is not None else 0)


def candidate(cid, executable=True, fits=True):
    return Candidate(cid, executable, ContextFit(100, 10, 110 if fits else 109, P.DERIVED))


def setup(latencies=(100, 180), tokens=(1000, 500), bin=SizeBin.SMALL):
    state = PolicyState("router", calibration={
        EstimateKey(cid, bin): PerformanceEstimate(est(latency), est(token))
        for cid, latency, token in zip((INLINE, LOCAL), latencies, tokens)
    })
    return state, (candidate(INLINE), candidate(LOCAL))


def features(index=1, bin=SizeBin.SMALL):
    return RequestFeatures(index, 1024, bin)


def obs(duration=10, tokens=100, provenance=P.REPORTED, cid=INLINE, bin=SizeBin.SMALL, status="success"):
    return Observation(cid, bin, status, duration,
                       TokenUsage(tokens, provenance if tokens is not None else P.UNAVAILABLE),
                       P.MEASURED if duration is not None else P.UNAVAILABLE)


@pytest.mark.parametrize("variant,bin", [("2k", SizeBin.SMALL), ("4k", SizeBin.SMALL),
                                          ("8k", SizeBin.LARGE), ("16k", SizeBin.LARGE)])
def test_nominal_mapping_is_outside_policy(variant, bin):
    assert prepare_request_features(1, 123, variant) == RequestFeatures(1, 123, bin)
    assert {f.name for f in fields(RequestFeatures)} == {"sequence_index", "context_bytes", "size_bin"}


@pytest.mark.parametrize("index,bytes,bin", [(0, 1, SizeBin.SMALL), (1, -1, SizeBin.SMALL), (1, 1, "small")])
def test_invalid_features(index, bytes, bin):
    with pytest.raises(ValueError):
        RequestFeatures(index, bytes, bin)


@pytest.mark.parametrize("value,provenance", [(-1, P.MEASURED), (float("nan"), P.REPORTED),
    (float("inf"), P.ESTIMATED), (None, P.REPORTED), (1, P.UNAVAILABLE)])
def test_metric_validation(value, provenance):
    with pytest.raises(ValueError):
        Estimate(value, provenance, 1)
    with pytest.raises(ValueError):
        TokenUsage(value, provenance)
    with pytest.raises(ValueError):
        Observation(INLINE, SizeBin.SMALL, "success", value, TokenUsage(None, P.UNAVAILABLE), provenance)


def test_context_fit_and_unique_candidate_contracts():
    assert candidate(INLINE).eligible
    assert candidate(INLINE, False, False).eligibility_reasons == ("not_executable", "context_capacity_exceeded")
    with pytest.raises(ValueError):
        ContextFit(100, 1, 100, P.REPORTED)
    with pytest.raises(ValueError):
        ContextFit(-1, 1, 100, P.ESTIMATED)
    state, candidates = setup()
    for policy in (RouterPolicy(state, PolicyConfig(150)), FixedPolicy(state, INLINE)):
        with pytest.raises(ValueError):
            policy.decide(features(), (candidates[0], candidates[0]))


@pytest.mark.parametrize("latencies,tokens,selected,attainment", [
    ((100, 180), (1000, 500), INLINE, "met"),
    ((100, 100), (1000, 500), LOCAL, "met"),
    ((220, 180), (1000, 500), LOCAL, "missed"),
    ((None, 180), (1, 500), LOCAL, "missed"),
    ((None, None), (1000, 1), INLINE, "unknown"),
    ((100, 100), (None, 500), LOCAL, "met"),
    ((100, 100), (None, None), INLINE, "met"),
    ((100, 100), (100, 100), INLINE, "met"),
    ((0, 0), (0, 0), INLINE, "met"),
])
def test_initial_selection(latencies, tokens, selected, attainment):
    state, candidates = setup(latencies, tokens)
    d = RouterPolicy(state, PolicyConfig(150), probes=False).decide(features(), tuple(reversed(candidates)))
    assert (d.selected_configuration, d.objective_attainment) == (selected, attainment)


@pytest.mark.parametrize("tokens,selected", [(91, INLINE), (90, LOCAL), (0, LOCAL)])
def test_material_improvement_boundary(tokens, selected):
    state, candidates = setup((100, 100), (100, 100))
    policy = RouterPolicy(state, PolicyConfig(150), probes=False)
    policy.decide(features(), candidates)
    state.calibration[EstimateKey(LOCAL, SizeBin.SMALL)] = PerformanceEstimate(est(100), est(tokens))
    assert policy.decide(features(7), candidates).selected_configuration == selected


@pytest.mark.parametrize("index,selected", [(2, INLINE), (6, INLINE), (7, LOCAL)])
def test_objective_priority_over_more_expensive_tokens_and_cooldown(index, selected):
    state, candidates = setup((100, 180), (100, 1000))
    policy = RouterPolicy(state, PolicyConfig(150), probes=False)
    policy.decide(features(), candidates)
    state.calibration[EstimateKey(INLINE, SizeBin.SMALL)] = PerformanceEstimate(est(200), est(100))
    state.calibration[EstimateKey(LOCAL, SizeBin.SMALL)] = PerformanceEstimate(est(100), est(1000))
    d = policy.decide(features(index), candidates)
    assert d.selected_configuration == selected
    if index == 7:
        assert d.reason == "objective_priority"


def test_real_incumbent_ineligibility_overrides_cooldown():
    state, candidates = setup()
    policy = RouterPolicy(state, PolicyConfig(150), probes=False)
    policy.decide(features(), candidates)
    d = policy.decide(features(2), (candidate(INLINE, fits=False), candidates[1]))
    assert d.selected_configuration == LOCAL and d.reason == "incumbent_ineligible"
    assert state.last_switch_sequence == 2


def test_zero_ties_and_unknown_latencies_retain_incumbent():
    state, candidates = setup((100, 100), (0, 0))
    state.incumbent = LOCAL
    policy = RouterPolicy(state, PolicyConfig(150), probes=False)
    assert policy.decide(features(), candidates).selected_configuration == LOCAL
    state.calibration.clear()
    d = policy.decide(features(7), candidates)
    assert d.selected_configuration == LOCAL and d.objective_attainment == "unknown"


@pytest.mark.parametrize("eligible_count", [0, 1, 2])
def test_probes_require_alternative_and_preserve_normal_state(eligible_count):
    state, candidates = setup()
    policy = RouterPolicy(state, PolicyConfig(150))
    for index in range(1, 65):
        d = policy.decide(features(index), candidates[:eligible_count])
        actual = eligible_count == 2 and index in {10, 20, 30, 40, 50, 60}
        assert d.probe == actual
        assert state.incumbent == (INLINE if eligible_count else None)
        assert state.last_switch_sequence == (1 if eligible_count else None)
        if actual:
            assert d.selected_configuration == LOCAL and d.normal_configuration == INLINE
    assert state.probe_count == (6 if eligible_count == 2 else 0)


def test_probe_commits_new_normal_selection_before_alternative_execution():
    state, candidates = setup()
    policy = RouterPolicy(state, PolicyConfig(150))
    policy.decide(features(), candidates)
    state.calibration[EstimateKey(LOCAL, SizeBin.SMALL)] = PerformanceEstimate(est(100), est(500))
    d = policy.decide(features(10), candidates)
    assert d.normal_configuration == LOCAL and d.selected_configuration == INLINE
    assert state.incumbent == LOCAL and state.last_switch_sequence == 10
    assert policy.decide(features(11), candidates).cooldown_active


@pytest.mark.parametrize("bin", list(SizeBin))
@pytest.mark.parametrize("count", [0, 2, 3])
def test_runtime_minimum_and_calibration_fallback(bin, count):
    state, _ = setup(bin=bin)
    policy = AdaptivePolicy(state, PolicyConfig(150))
    for _ in range(count):
        policy.observe(obs(bin=bin))
    key = EstimateKey(INLINE, bin)
    current = state.estimates.get(key, state.calibration[key])
    assert current.latency_ms.value == (10 if count == 3 else 100)
    assert current.total_tokens.value == (100 if count == 3 else 1000)
    if count == 3:
        assert current.latency_ms.provenance == P.DERIVED
        assert current.total_tokens.source_provenance == (P.REPORTED,) * 3


def test_per_metric_minimum_partial_availability_and_rolling_eviction():
    state, _ = setup()
    policy = AdaptivePolicy(state, PolicyConfig(150))
    for token in (100, 200, None):
        policy.observe(obs(tokens=token))
    key = EstimateKey(INLINE, SizeBin.SMALL)
    assert state.estimates[key].latency_ms.value == 10
    assert state.estimates[key].total_tokens.value == 1000
    policy.observe(obs(tokens=300))
    assert state.estimates[key].total_tokens.value == 200
    for duration in (40, 50, 60, 70, 80):
        policy.observe(obs(duration, tokens=None))
    assert state.estimates[key].latency_ms.value == 60
    assert state.estimates[key].latency_ms.observation_count == 5
    assert state.estimates[key].total_tokens.value == 1000
    policy.observe(obs(999, 999, status="error"))
    assert state.estimates[key].latency_ms.value == 60
    assert len(state.recent_observations[key]) == 10


def test_no_calibration_and_partial_latency_availability():
    state = PolicyState("adaptive")
    policy = AdaptivePolicy(state, PolicyConfig(150))
    for _ in range(3):
        policy.observe(obs(None, 100))
    current = state.estimates[EstimateKey(INLINE, SizeBin.SMALL)]
    assert current.latency_ms.value is None and current.latency_ms.provenance == P.UNAVAILABLE
    assert current.total_tokens.value == 100


def test_shared_estimator_provenance_and_key_validation():
    observations = [obs(n, n, P.REPORTED if n < 3 else P.ESTIMATED) for n in (1, 2, 3)]
    result = estimate_from_observations(observations)
    assert result.latency_ms.value == 2 and result.latency_ms.provenance == P.DERIVED
    assert result.total_tokens.provenance == P.ESTIMATED
    assert result.total_tokens.source_provenance == (P.REPORTED, P.REPORTED, P.ESTIMATED)
    assert estimate_from_observations([obs(n) for n in range(1, 8)]).latency_ms.value == 5
    for other in (obs(cid=LOCAL), obs(bin=SizeBin.LARGE)):
        with pytest.raises(ValueError):
            estimate_from_observations([obs(), other])


def test_episode_and_arm_state_independence_and_observation_ownership():
    original, candidates = setup()
    frozen_state = PolicyState("frozen", calibration=original.calibration)
    adaptive_state = PolicyState("adaptive", calibration=original.calibration)
    fixed_state = PolicyState("fixed", calibration=original.calibration)
    policies = (RouterPolicy(frozen_state, PolicyConfig(150)),
                AdaptivePolicy(adaptive_state, PolicyConfig(150)), FixedPolicy(fixed_state, INLINE))
    for policy in policies:
        for _ in range(3):
            policy.observe(obs())
    assert frozen_state.estimates == fixed_state.estimates == {}
    assert adaptive_state.estimates
    assert not original.recent_observations
    original.calibration.clear()
    assert frozen_state.calibration and adaptive_state.calibration
    policies[0].decide(features(), candidates)
    assert adaptive_state.incumbent is None
    assert PolicyState("new", calibration=frozen_state.calibration).incumbent is None


def test_frozen_and_adaptive_identical_mechanics_with_identical_estimates():
    state, candidates = setup((100, 100), (100, 100))
    frozen = RouterPolicy(PolicyState("frozen", calibration=state.calibration), PolicyConfig(150))
    adaptive = AdaptivePolicy(PolicyState("adaptive", calibration=state.calibration), PolicyConfig(150))
    for index in range(1, 65):
        a, b = frozen.decide(features(index), candidates), adaptive.decide(features(index), candidates)
        assert (a.selected_configuration, a.normal_configuration, a.probe, a.cooldown_active) == (
            b.selected_configuration, b.normal_configuration, b.probe, b.cooldown_active)
        observation = obs(100, 100, cid=a.selected_configuration)
        frozen.observe(observation)
        adaptive.observe(observation)
    assert frozen.state.estimates == {} and adaptive.state.estimates
    assert frozen.state.probe_count == adaptive.state.probe_count == 6


def test_fixed_ineligibility_and_unserved():
    state, candidates = setup()
    fixed = FixedPolicy(state, INLINE)
    d = fixed.decide(features(10), (candidate(INLINE, executable=False), candidates[1]))
    assert d.selected_configuration is None and not d.probe
    assert RouterPolicy(state, PolicyConfig(150)).decide(features(), ()).selected_configuration is None


@pytest.mark.parametrize("status", ["selected", "success", "error", "unserved"])
def test_decision_sidecar_round_trip(status):
    state, candidates = setup()
    decision = RouterPolicy(state, PolicyConfig(150)).decide(features(), () if status == "unserved" else candidates)
    sidecar = DecisionSidecar(request_id="request-1", trial_id=None if status == "unserved" else "trial-1",
        policy="frozen-router", policy_version=POLICY_VERSION, decision=DecisionRecord.from_decision(decision),
        status=status, end_to_end_duration_ms={"value": 12 if status in {"success", "error"} else None,
            "provenance": P.MEASURED if status in {"success", "error"} else P.UNAVAILABLE, "observationCount": 1},
        tokens={"value": None, "provenance": P.UNAVAILABLE}, error="failed" if status == "error" else None)
    encoded = sidecar.model_dump_json()
    assert DecisionSidecar.model_validate_json(encoded) == sidecar
    payload = json.loads(encoded)
    assert payload["schemaVersion"] == 1 and payload["requestId"] == "request-1"
    assert payload["decision"]["features"]["sizeBin"] == "small"
    assert "latencyMs" in payload["decision"]["estimates"].get(INLINE, {"latencyMs": None})
    if status != "unserved":
        assert payload["decision"]["candidates"][0]["contextFit"]["inputTokens"] == 100


def test_run_metadata_round_trip_and_forbidden_policy_fields():
    run = RunMetadata(policy="adaptive-router", policy_version=POLICY_VERSION, scenario="stationary", seed=1,
        dataset_provenance={"hash": "abc"}, model_provenance={"model": "mock"},
        configuration_catalog={INLINE: {"strategy": "inline"}}, latency_objective_ms=100,
        injection_schedule=(), cache_policy={"isolation": "seed"}, code_revision="abc")
    assert RunMetadata.model_validate_json(run.model_dump_json()) == run
    assert "configurationCatalog" in run.model_dump()
    forbidden = {"request_id", "trial_id", "task_text", "target_identity", "oracle", "evaluation_result", "phase", "scenario"}
    for cls in (RequestFeatures, Candidate, Observation, Decision):
        assert not forbidden.intersection(f.name for f in fields(cls))


@pytest.mark.parametrize("latencies,tokens", [((200, 200), (100, 100)), ((100, 100), (100, 100))])
def test_known_metric_replaces_missing_incumbent_metric_after_cooldown(latencies, tokens):
    state, candidates = setup(latencies, tokens)
    state.incumbent = INLINE
    state.last_switch_sequence = 1
    old = state.calibration[EstimateKey(INLINE, SizeBin.SMALL)]
    state.calibration[EstimateKey(INLINE, SizeBin.SMALL)] = (
        PerformanceEstimate(est(None), old.total_tokens) if latencies[0] > 150
        else PerformanceEstimate(old.latency_ms, est(None)))
    policy = RouterPolicy(state, PolicyConfig(150), probes=False)
    assert policy.decide(features(6), candidates).selected_configuration == INLINE
    assert policy.decide(features(7), candidates).selected_configuration == LOCAL


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1])
def test_invalid_objectives(invalid):
    with pytest.raises(ValueError):
        PolicyConfig(invalid)


def test_runtime_updates_are_isolated_by_configuration_and_bin():
    state, _ = setup()
    policy = AdaptivePolicy(state, PolicyConfig(150))
    for _ in range(3):
        policy.observe(obs(bin=SizeBin.LARGE, cid=LOCAL))
    assert set(state.estimates) == {EstimateKey(LOCAL, SizeBin.LARGE)}
    assert state.calibration[EstimateKey(INLINE, SizeBin.SMALL)].latency_ms.value == 100


def test_mixed_latency_sources_remain_estimated():
    observations = [obs() for _ in range(2)]
    observations.append(Observation(INLINE, SizeBin.SMALL, "success", 10,
                                    TokenUsage(100, P.REPORTED), P.ESTIMATED))
    result = estimate_from_observations(observations)
    assert result.latency_ms.provenance == P.ESTIMATED
    assert result.latency_ms.source_provenance == (P.MEASURED, P.MEASURED, P.ESTIMATED)


def test_sidecar_rejects_inconsistent_outcomes_and_non_measured_duration():
    state, candidates = setup()
    record = DecisionRecord.from_decision(RouterPolicy(state, PolicyConfig(150)).decide(features(), candidates))
    data = dict(request_id="r", trial_id="t", policy="frozen", policy_version=POLICY_VERSION,
        decision=record, status="selected", end_to_end_duration_ms={"value": None,
        "provenance": P.UNAVAILABLE, "observationCount": 0}, tokens={"value": None, "provenance": P.UNAVAILABLE})
    for patch in ({"status": "unserved"}, {"trial_id": None}, {"status": "error"},
                  {"end_to_end_duration_ms": {"value": 1, "provenance": P.ESTIMATED, "observationCount": 1}},
                  {"schema_version": 2}):
        with pytest.raises(ValueError):
            DecisionSidecar(**(data | patch))


@pytest.mark.parametrize("latency,selected", [(182, INLINE), (180, LOCAL)])
def test_latency_improvement_threshold_when_objective_is_missed(latency, selected):
    state, candidates = setup((200, 200))
    policy = RouterPolicy(state, PolicyConfig(150), probes=False)
    policy.decide(features(), candidates)
    state.calibration[EstimateKey(LOCAL, SizeBin.SMALL)] = PerformanceEstimate(est(latency), est(500))
    assert policy.decide(features(7), candidates).selected_configuration == selected
