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
