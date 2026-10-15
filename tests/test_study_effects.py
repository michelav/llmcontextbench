"""Phase-oracle, random and pacing policies; fault and token-quota effects."""
from pathlib import Path

import pytest

from ctxbench.adaptive.recovery import sealed_read
from ctxbench.adaptive.study_policy import Controller
from ctxbench.adaptive.study_runner import run
from ctxbench.ai.models.base import ToolResult
from ctxbench.studies import study
from tests.test_study_protocol import frozen, make_study, mock_execute  # noqa: F401  (fixture reuse)

INLINE, MCP = 'inline-code-full', 'local-mcp-repoqa-ops'


def prepared(tmp_path, frozen, name, **overrides):
    return sealed_read(Path(study.prepare(definition=make_study(tmp_path, frozen, comparisons=[], **overrides),
                                          output=tmp_path/name)['prepared']))


def test_schedule_policy_follows_phases(frozen, tmp_path):
    plan = prepared(tmp_path, frozen, 'schedule', policies={'oracle': {'type': 'schedule',
        'default': {'small': INLINE, 'large': MCP},
        'phases': [{'firstRequest': 3, 'lastRequest': 4, 'configurationBySize': {'small': MCP, 'large': INLINE}}]}})
    controller = Controller(plan, plan['episodes'][0])
    for index, instance in enumerate(plan['episodes'][0]['workload'][:6]):
        size = plan['requests'][instance]['sizeBin']
        in_phase = 3 <= index+1 <= 4
        expected = {'small': MCP, 'large': INLINE} if in_phase else {'small': INLINE, 'large': MCP}
        assert controller.decide(index) == {'configuration': expected[size], 'reason': 'schedule', 'probe': False}


def test_schedule_rejects_phase_beyond_workload(frozen, tmp_path):
    definition = make_study(tmp_path, frozen, comparisons=[], policies={'oracle': {'type': 'schedule',
        'default': {'small': INLINE}, 'phases': [{'firstRequest': 1, 'lastRequest': 999,
                                                  'configurationBySize': {'small': MCP}}]}})
    with pytest.raises(ValueError, match='schedule phase exceeds workload'):
        study.prepare(definition=definition, output=tmp_path/'bad-schedule')


def test_random_policy_is_seeded_and_eligible(frozen, tmp_path):
    plan = prepared(tmp_path, frozen, 'random', policies={'random': {'type': 'random-eligible', 'seed': 7}})
    def sequence():
        controller = Controller(plan, plan['episodes'][0])
        return [controller.decide(i)['configuration'] for i in range(20)]
    first, again = sequence(), sequence()
    assert first == again and set(first) == {INLINE, MCP}


def test_pace_serves_every_request_within_budget(frozen, tmp_path):
    plan = prepared(tmp_path, frozen, 'pace', latencyLimitMs=None, tokenBudget=700, policies={
        'pace': {'type': 'budget', 'mode': 'pace', 'forecast': 'expected', 'probeInterval': 1000},
        'inline': {'type': 'fixed', 'configuration': INLINE}, 'mcp': {'type': 'fixed', 'configuration': MCP}})
    for size in ('small', 'large'):
        plan['estimates'][INLINE][size].update(latencyMs=10, tokens=20)
        plan['estimates'][MCP][size].update(latencyMs=100, tokens=5)
    def execution(trial, engine, **kwargs):
        result = mock_execute(trial, engine)
        return result.model_copy(update={'usage': {'totalTokens': 20 if trial.configurationId == INLINE else 5}})
    episode = plan['episodes'][0]
    packets = run(plan, episode, tmp_path/'pace-run', execution=execution)
    chosen = [p['selection']['configuration'] for p in packets]
    assert None not in chosen and {INLINE, MCP} == set(chosen)
    assert chosen[0] == INLINE and chosen[-1] == MCP
    assert packets[-1]['ledger']['knownTokens'] <= 700


def test_pace_serves_cheapest_once_the_reserve_is_reached(frozen, tmp_path):
    plan = prepared(tmp_path, frozen, 'pace-reserve', latencyLimitMs=None, tokenBudget=2000, policies={
        'pace': {'type': 'budget', 'mode': 'pace', 'forecast': 'expected', 'probeInterval': 1000},
        'inline': {'type': 'fixed', 'configuration': INLINE}, 'mcp': {'type': 'fixed', 'configuration': MCP}})
    for size in ('small', 'large'):
        plan['estimates'][INLINE][size].update(latencyMs=10, tokens=40)
        plan['estimates'][MCP][size].update(latencyMs=100, tokens=10 if size == 'small' else 30)
    controller = Controller(plan, plan['episodes'][0])
    workload = plan['episodes'][0]['workload']
    large = next(i for i, instance in enumerate(workload) if plan['requests'][instance]['sizeBin'] == 'large')
    # No slack beyond the cheapest plan for the rest: a large request exceeds the mean reserve.
    controller.consumed = 2000 - min(controller._forecast(c, large+1) for c in (INLINE, MCP))
    decision = controller.decide(large)
    assert decision['configuration'] == MCP and decision['reason'] in ('paced', 'paced_reserve')
    controller.consumed = 2000 - 5
    assert controller.decide(large)['configuration'] is None


class FakeRuntime:
    def list_tools(self):
        return []

    def call_tool(self, name, arguments):
        return ToolResult(name=name, content='ok', is_error=False, metadata={})

    def close(self):
        pass


def calling_execution(calls=10):
    def execution(trial, engine, **kwargs):
        decorate = kwargs.get('local_mcp_runtime_decorator')
        if decorate:
            runtime = decorate(FakeRuntime())
            for _ in range(calls):
                runtime.call_tool('read_file', {})
        return mock_execute(trial, engine)
    return execution


def test_fault_injection_is_seeded_and_recorded(frozen, tmp_path):
    fault = {'kind': 'fault', 'configuration': MCP, 'toolErrorRate': 0.5, 'seed': 3,
             'firstRequest': 1, 'lastRequest': 4}
    plan = prepared(tmp_path, frozen, 'fault', scenarios={'faulty': [fault]},
                    policies={'mcp': {'type': 'fixed', 'configuration': MCP}}, latencyLimitMs=None)
    counts = []
    for name in ('one', 'two'):
        packets = run(plan, plan['episodes'][0], tmp_path/f'fault-{name}', execution=calling_execution())
        counts.append([p['decision']['faultsInjected'] for p in packets])
    assert counts[0] == counts[1]
    assert all(0 < n < 10 for n in counts[0][:4]) and set(counts[0][4:]) == {0}


def test_fault_requires_local_mcp(frozen, tmp_path):
    fault = {'kind': 'fault', 'configuration': INLINE, 'toolErrorRate': 0.5, 'seed': 3,
             'firstRequest': 1, 'lastRequest': 4}
    with pytest.raises(ValueError, match='fault injection requires local_mcp'):
        prepared(tmp_path, frozen, 'bad-fault', scenarios={'faulty': [fault]})


def test_token_quota_waits_inside_measured_time(frozen, tmp_path):
    quota = {'kind': 'token-quota', 'tokensPerMinute': 1500, 'firstRequest': 1, 'lastRequest': 3}
    plan = prepared(tmp_path, frozen, 'quota', scenarios={'quota': [quota]},
                    policies={'inline': {'type': 'fixed', 'configuration': INLINE}}, latencyLimitMs=None)
    clock = [0.0]
    def sleeper(seconds):
        clock[0] += seconds
    def execution(trial, engine, **kwargs):
        result = mock_execute(trial, engine)
        return result.model_copy(update={'usage': {'totalTokens': 1000}})
    packets = run(plan, plan['episodes'][0], tmp_path/'quota-run', execution=execution,
                  monotonic=lambda: clock[0], sleeper=sleeper)
    waits = [round(p['decision']['quotaWaitMs']) for p in packets[:4]]
    assert waits == [0, 0, 60000, 0]
    assert round(packets[2]['decision']['durationMs']) == 60000
    assert all(p['decision']['controllerMs'] >= 0 for p in packets)


def test_legacy_scenario_entries_still_validate(frozen, tmp_path):
    delay = {'configuration': MCP, 'scope': 'tool-call', 'delayMs': 5, 'firstRequest': 1, 'lastRequest': 2}
    plan = prepared(tmp_path, frozen, 'legacy-delay', scenarios={'delayed': [delay]})
    assert plan['episodes'][0]['scenario'][0]['kind'] == 'delay'


def test_analysis_reports_all_request_quality_paired_metrics_and_arms(frozen, tmp_path):
    import json
    from ctxbench.adaptive.study_runner import load_packets
    definition = make_study(tmp_path, frozen, latencyLimitMs=1000, comparisons=[['mcp', 'inline']], policies={
        'inline': {'type': 'fixed', 'configuration': INLINE}, 'mcp': {'type': 'fixed', 'configuration': MCP}})
    path = Path(study.prepare(definition=definition, output=tmp_path/'analysis-study')['prepared'])
    plan = sealed_read(path)
    for episode in plan['episodes']:
        study.episode(prepared=path, policy=episode['policyName'], scenario='stationary', seed=201, repeat=1,
                      execution=mock_execute)
        root = path.parent/'episodes'/episode['id']
        packets = load_packets(root)
        # Every request passes except the first; evaluation rows are written as `llmctxbench eval` would.
        rows = [{'trialId': p['result']['trialId'], 'outcome': {'passed': i > 0}} for i, p in enumerate(packets)]
        (root/'evals.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    report = study.analyze(path, bootstrap_replicates=20)
    planned = len(plan['episodes'][0]['workload'])
    for summary in report['summaries']:
        assert summary['passRateAllRequests'] == (planned-1)/planned
        assert summary['switches'] == 0 and len(summary['phaseSummaries']) == 1
    comparison = report['comparisons'][0]
    assert set(comparison['metrics']) == {'latencyMs', 'deadlineMiss', 'tokensLowerBound', 'failure', 'passed'}
    assert comparison['metrics']['passed']['meanDifference'] == 0
    assert {(a['policyName'], a['episodes']) for a in report['arms']} == {('inline', 1), ('mcp', 1)}
    assert any(p.startswith('analysis/tradeoff-') for p in report['plots'])


def test_lags_measure_reaction_and_recovery():
    from ctxbench.studies.replay import _lags
    route = ['A']*10 + ['A', 'A', 'B', 'B'] + ['B']*6 + ['B', 'A'] + ['A']*3
    rows = [{'sequenceIndex': i+1, 'probe': False, 'configuration': c} for i, c in enumerate(route)]
    effect = {'kind': 'delay', 'configuration': 'A', 'firstRequest': 11, 'lastRequest': 20}
    assert _lags(rows, [effect]) == [{'configuration': 'A', 'reactionLag': 2, 'recoveryLag': 1}]
