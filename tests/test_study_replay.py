"""Provider-free replay: real Controller over resampled calibration observations."""
import json
from pathlib import Path

import pytest

from ctxbench.studies import replay
from tests.test_study_protocol import frozen  # noqa: F401  (fixture reuse)

INLINE, MCP = 'inline-code-full', 'local-mcp-repoqa-ops'


def grid(tmp_path, points, policies=None, **extra):
    spec = {'schemaVersion': 1, 'seeds': [1, 2], 'replicates': 2, 'base': {'latencyLimitMs': 1000},
            'policies': policies or {'inline': {'type': 'fixed', 'configuration': INLINE},
                                     'mcp': {'type': 'fixed', 'configuration': MCP},
                                     'frozen': {'type': 'router', 'adaptive': False},
                                     'adaptive': {'type': 'router', 'adaptive': True}},
            'points': points, **extra}
    path = tmp_path/f'grid-{len(list(tmp_path.glob("grid-*")))}.json'
    path.write_text(json.dumps(spec))
    return path


def test_replay_is_deterministic(frozen, tmp_path):
    path = grid(tmp_path, [{'name': 'stationary'}])
    first = replay.replay(grid=path, baseline=frozen)
    assert replay.replay(grid=path, baseline=frozen) == first
    assert first['provenance'] == 'estimated' and first['pool'] == 'calibration'


def test_fixed_arms_reproduce_pool_without_effects(frozen, tmp_path):
    report = replay.replay(grid=grid(tmp_path, [{'name': 'stationary'}]), baseline=frozen)
    pool = replay.load_pool(replay.plan_from_baseline(frozen))
    policies = report['points'][0]['policies']
    for name, cid in (('inline', INLINE), ('mcp', MCP)):
        samples = [s['durationMs'] for (c, _), rows in pool.items() if c == cid for s in rows]
        assert min(samples) <= policies[name]['meanLatencyMs'] <= max(samples)
        assert policies[name]['failures'] == 0 and policies[name]['switches'] == 0


def test_tool_call_delay_scales_with_recorded_tool_calls(frozen, tmp_path):
    delay = {'configuration': MCP, 'scope': 'tool-call', 'delayMs': 5000, 'firstRequest': 10, 'lastRequest': 40}
    oracle = {'type': 'schedule', 'default': {'small': MCP, 'large': MCP},
              'phases': [{'firstRequest': 10, 'lastRequest': 40, 'configurationBySize': {'small': INLINE, 'large': INLINE}}]}
    plan = replay.plan_from_baseline(frozen)
    pool = replay.load_pool(plan)
    for rows in pool.values():
        for row in rows:
            row['toolCalls'] = 3
    path = grid(tmp_path, [{'name': 'degraded', 'latencyLimitMs': 10000, 'effects': [delay],
                            'policies': {'oracle': oracle}}])
    # The fixture pool has no tool calls recorded, so inject them through the loader.
    original = replay.load_pool
    replay.load_pool = lambda _plan: pool
    try:
        report = replay.replay(grid=path, baseline=frozen)
    finally:
        replay.load_pool = original
    point = report['points'][0]
    assert point['reference'] == 'frozen'
    assert point['policies']['mcp']['deadlineMisses'] >= 30


def test_replay_requires_one_source(frozen, tmp_path):
    with pytest.raises(ValueError, match='exactly one'):
        replay.replay(grid=grid(tmp_path, [{'name': 's'}]))


def test_counterfactual_cascade_pairs_fixed_arms(tmp_path):
    root = tmp_path/'study'
    episodes = []
    for policy in ('lean', 'default'):
        episode = {'id': f'e-{policy}', 'policyName': policy, 'seed': 1, 'repeat': 1}
        episodes.append(episode)
        rows = [{'requestId': f'r{i}', 'status': 'error' if (policy == 'lean' and i == 0) else 'success',
                 'durationMs': 100, 'tokens': {'value': None if (policy == 'lean' and i == 0) else 10,
                                               'knownPartial': 7 if (policy == 'lean' and i == 0) else None}}
                for i in range(3)]
        directory = root/'episodes'/episode['id']
        directory.mkdir(parents=True)
        (directory/'decisions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    from ctxbench.adaptive.recovery import sealed_write
    sealed_write(root/'prepared.json', {'episodes': episodes})
    report = replay.counterfactual_cascade(study_dir=root, primary='lean', fallback='default')
    assert report['failures'] == 0 and report['fallbacks'] == 1 and report['requests'] == 3
    assert report['tokensLowerBoundPerRequest'] == pytest.approx((7+10+10+10)/3)
    assert report['heldOutDebug'] is True


# Size-blind router and burst workloads.
from ctxbench.adaptive.study_policy import Controller  # noqa: E402
from ctxbench.studies.models import BlindRouterPolicy, WorkloadShape  # noqa: E402

I, D = 'inline', 'direct'
COST = {I: {'small': (3000, 2000), 'large': (3500, 50000)}, D: {'small': (4500, 3000), 'large': (4800, 3800)}}


def blind_plan(sizes, budget=10000, window=10):
    fit = {'executable': True, 'context_fit': {'input_tokens': 1, 'output_reservation': 1, 'context_limit': 10}}
    return {'configurations': [I, D],
            'definition': {'latencyLimitMs': 8000, 'tokenRateBudget': {'perRequest': budget, 'window': window}},
            'estimates': {c: {s: {'latencyMs': v[0], 'tokens': v[1]} for s, v in COST[c].items()} for c in COST},
            'calibrationSizeMix': {'small': 0.5, 'large': 0.5},
            'tokenQuantiles': {c: {s: {'p95': v[1]} for s, v in COST[c].items()} for c in COST},
            'requests': {f'r{i}': {'sizeBin': size, 'candidates': {I: fit, D: fit}} for i, size in enumerate(sizes)}}


def drive(sizes, policy, **plan_options):
    plan = blind_plan(sizes, **plan_options)
    policy = BlindRouterPolicy.model_validate(policy).model_dump()
    controller = Controller(plan, {'policy': policy, 'workload': list(plan['requests']), 'seed': 1, 'repeat': 1})
    decisions = []
    for index, size in enumerate(sizes):
        decision = controller.decide(index)
        latency, tokens = COST[decision['configuration']][size]
        controller.observe({'configuration': decision['configuration'], 'sizeBin': size, 'status': 'success',
                            'durationMs': latency, 'tokens': {'value': tokens, 'knownPartial': None},
                            'failures': [], 'sequenceIndex': index+1})
        decisions.append(decision)
    return decisions


BURST = ['small']*10 + ['large']*15 + ['small']*20
PERIODIC = {'type': 'blind-router', 'adaptive': True, 'probeTriggers': ['periodic'], 'probeInterval': 5}


def test_blind_router_leaves_on_a_burst_and_returns_through_a_probe():
    decisions = drive(BURST, PERIODIC)
    routed = [d['configuration'] for d in decisions]
    assert routed[:10] == [I]*10
    left = next(i for i in range(10, 25) if routed[i] == D and not decisions[i]['probe'])
    assert left - 10 <= 2
    assert any(d['probe'] for d in decisions[10:25])
    back = next(i for i in range(25, 45) if routed[i] == I and not decisions[i]['probe'])
    assert back - 25 <= 6


def test_blind_router_never_reads_request_size():
    sizes = ['small']*5 + ['large']*5
    relabelled = blind_plan(['large']*10)
    plan = blind_plan(sizes)
    policy = BlindRouterPolicy.model_validate(PERIODIC).model_dump()
    runs = []
    for p in (plan, relabelled):
        controller = Controller(p, {'policy': policy, 'workload': list(p['requests']), 'seed': 1, 'repeat': 1})
        out = []
        for index, size in enumerate(sizes):
            # Observations follow the true sizes; only the plan's labels differ.
            d = controller.decide(index)
            latency, tokens = COST[d['configuration']][size]
            controller.observe({'configuration': d['configuration'], 'sizeBin': 'small', 'status': 'success',
                                'durationMs': latency, 'tokens': {'value': tokens, 'knownPartial': None},
                                'failures': [], 'sequenceIndex': index+1})
            out.append(d)
        runs.append(out)
    assert runs[0] == runs[1]


def test_budget_guard_defers_probes_until_the_window_can_absorb_one():
    unguarded = drive(BURST, {**PERIODIC, 'probeInterval': 1})
    guarded = drive(BURST, {**PERIODIC, 'probeInterval': 1, 'budgetGuard': True})
    assert sum(d['probe'] for d in guarded[10:25]) < sum(d['probe'] for d in unguarded[10:25])


def test_signal_trigger_probes_only_when_the_incumbent_looks_small():
    policy = {'type': 'blind-router', 'adaptive': True, 'probeTriggers': ['signal'],
              'signalTokens': 3400, 'signalWindow': 3}
    decisions = drive(BURST, policy)
    assert not any(d['probe'] for d in decisions[10:25])
    assert any(d['probe'] for d in decisions[25:]) and decisions[-1]['configuration'] == I


def test_backoff_spaces_failed_probes():
    long_burst = ['small']*5 + ['large']*60
    plain = drive(long_burst, PERIODIC)
    backoff = drive(long_burst, {**PERIODIC, 'probeBackoff': True})
    assert sum(d['probe'] for d in backoff) < sum(d['probe'] for d in plain)


def test_non_adaptive_blind_router_is_static_and_does_not_probe():
    decisions = drive(BURST, {'type': 'blind-router', 'adaptive': False})
    assert len({d['configuration'] for d in decisions}) == 1 and not any(d['probe'] for d in decisions)
    with pytest.raises(ValueError, match='does not probe'):
        BlindRouterPolicy.model_validate({'type': 'blind-router', 'adaptive': False, 'probeTriggers': ['periodic']})
    with pytest.raises(ValueError, match='signalTokens'):
        BlindRouterPolicy.model_validate({'type': 'blind-router', 'adaptive': True, 'probeTriggers': ['signal']})



def test_no_probe_ablation_differs_from_periodic_only_in_probing():
    periodic = drive(BURST, PERIODIC)
    no_probe = drive(BURST, {'type': 'blind-router', 'adaptive': True, 'probeTriggers': []})
    first_probe = next(i for i, d in enumerate(periodic) if d['probe'])
    assert no_probe[:first_probe] == periodic[:first_probe]
    assert not any(d['probe'] for d in no_probe)
    # Without probes the inactive configuration's knowledge is never refreshed: no return after the burst.
    left = next(i for i, d in enumerate(no_probe) if d['configuration'] == D)
    assert 10 <= left <= 12 and all(d['configuration'] == D for d in no_probe[left:])

def test_shaped_workload_follows_phases_and_is_deterministic():
    plan = {'requests': {f't{t}_ctx{s}': {'target': f't{t}', 'sizeBin': 'small' if s == '2k' else 'large'}
                         for t in range(3) for s in ('2k', '64k')}}
    shape = WorkloadShape.model_validate({'phases': [
        {'lastRequest': 4, 'sizeWeights': {'2k': 1}},
        {'lastRequest': 10, 'sizeWeights': {'large': 1}, 'disturbance': True}]}).model_dump()
    workload = replay.shaped_workload(plan, ['t0', 't1'], shape, seed=3)
    assert workload == replay.shaped_workload(plan, ['t0', 't1'], shape, seed=3)
    assert len(workload) == 10 and all(i.endswith('_ctx2k') for i in workload[:4])
    assert all(i.endswith('_ctx64k') and not i.startswith('t2') for i in workload[4:])
    with pytest.raises(ValueError, match='strictly increasing'):
        WorkloadShape.model_validate({'phases': [{'lastRequest': 4, 'sizeWeights': {'2k': 1}},
                                                 {'lastRequest': 4, 'sizeWeights': {'2k': 1}}]})


def test_replay_reports_budget_excess_and_burst_lags(frozen, tmp_path):
    policies = {'inline': {'type': 'fixed', 'configuration': INLINE},
                'blind': {'type': 'blind-router', 'adaptive': True, 'probeTriggers': ['periodic'], 'probeInterval': 5}}
    path = grid(tmp_path, [{'name': 'burst', 'tokenRateBudget': {'perRequest': 10**9, 'window': 4}}],
                policies=policies, workload={'phases': [{'lastRequest': 6, 'sizeWeights': {'small': 1}},
                                                       {'lastRequest': 12, 'sizeWeights': {'large': 1}, 'disturbance': True}]})
    report = replay.replay(grid=path, baseline=frozen)
    point = report['points'][0]
    assert point['workload']['phases'][1]['disturbance'] is True
    assert point['policies']['inline']['budgetExcess'] == 0 and point['policies']['inline']['requests'] == 12
    assert 'probeTokens' in point['policies']['blind']


def test_replay_order_reuses_every_request_once_and_reports_phase_excess(frozen, tmp_path):
    from ctxbench.adapters.repoqa.study import ordered_workload
    from ctxbench.studies.ordering import ordered
    plan = replay.plan_from_baseline(frozen)
    rows = [{**r, 'sizeBin': plan['requests'][r['instanceId']]['sizeBin']}
            for r in ordered_workload(plan['index'], plan['split']['heldOut'], 1)]
    small = sum(r['sizeBin'] == 'small' for r in rows)
    order = {'phases': [{'lastRequest': small, 'sizes': ['small']},
                        {'lastRequest': len(rows), 'sizes': ['large'], 'disturbance': True}]}
    workload = ordered(rows, order, 1, 'burst')
    assert sorted(workload) == sorted(r['instanceId'] for r in rows)
    path = grid(tmp_path, [{'name': 'p', 'scenario': 'burst', 'order': order,
                            'tokenRateBudget': {'perRequest': 10**9, 'window': 4}}],
                policies={'inline': {'type': 'fixed', 'configuration': INLINE}})
    point = replay.replay(grid=path, baseline=frozen)['points'][0]
    assert point['order']['phases'][1]['disturbance'] is True
    assert point['policies']['inline']['phaseExcess'] == [0, 0]
