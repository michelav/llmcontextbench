"""Write the SEAMS v2 replay grids and study definitions from one place.

Policies and scenario parameters are defined here once, so replay grids, pilots and
live study definitions cannot drift apart. Re-run after editing; outputs are
deterministic JSON under examples/studies/.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'examples' / 'studies'
BASELINE = '../../baselines/repoqa-long64-v2/frozen.json'

INLINE, MCP, MCP_LEAN = 'inline-code-full', 'local-mcp-default', 'local-mcp-lean'
FN, FN_LEAN = 'local-function-default', 'local-function-lean'
BINS = ('small', 'medium', 'large')

# Provisional v2 router: selected by replay on v1 calibration (round-robin probes every
# 10 requests, 12-request estimate TTL). Re-select on v2 calibration before collection.
V2 = {'type': 'router', 'adaptive': True, 'estimator': 'pooled-ratio', 'incumbentScope': 'bin',
      'latencyQuantile': 0.9, 'switchOnObjectiveMiss': True, 'cooldownRequests': 2,
      'updateWindow': 4, 'minimumObservations': 2, 'probeInterval': 10, 'estimateTtlRequests': 12}
V1 = {'type': 'router', 'adaptive': True}
FROZEN = {'type': 'router', 'adaptive': False, 'incumbentScope': 'bin', 'latencyQuantile': 0.9}
V2_CANDIDATES = {
    'v2-rr10-ttl12': {},
    'v2-rr10-ttl8': {'estimateTtlRequests': 8},
    'v2-t8-ttl8': {'probeMode': 'targeted', 'avoidedProbeInterval': 8, 'estimateTtlRequests': 8},
    'v2-t10-ttl10': {'probeMode': 'targeted', 'avoidedProbeInterval': 10, 'estimateTtlRequests': 10},
}
ABLATIONS = {
    'per-bin-mean': {'estimator': 'per-bin-mean'}, 'no-ttl': {'estimateTtlRequests': None},
    'mean-routing': {'latencyQuantile': None}, 'global-scope': {'incumbentScope': 'global'},
    'no-objective-first': {'switchOnObjectiveMiss': False}, 'cooldown-5': {'cooldownRequests': 5},
    'targeted-every-2': {'probeMode': 'targeted', 'avoidedProbeInterval': 2},
}

# S-A: MCP tool-call delay during requests 31-60 of 96; inline is the feasible fallback.
SA_LIMIT_MS, SA_DELAY_MS, SA_FIRST, SA_LAST = 10000, 2000, 31, 60
NORMAL_ROUTE = {'small': INLINE, 'medium': MCP, 'large': MCP}


def variant(base, change):
    return {k: v for k, v in {**base, **change}.items() if v is not None}


def mcp_delay(first, last, delay=SA_DELAY_MS):
    return {'kind': 'delay', 'configuration': MCP, 'scope': 'tool-call', 'delayMs': delay,
            'firstRequest': first, 'lastRequest': last}


def oracle(first, last, during, default=NORMAL_ROUTE):
    return {'type': 'schedule', 'default': default,
            'phases': [{'firstRequest': first, 'lastRequest': last, 'configurationBySize': during}]}


def degradation_grid():
    policies = {'inline': {'type': 'fixed', 'configuration': INLINE}, 'mcp': {'type': 'fixed', 'configuration': MCP},
                'frozen': FROZEN, 'v1': V1}
    policies.update({name: variant(V2, change) for name, change in V2_CANDIDATES.items()})
    policies.update({f'v2-{name}': variant(V2, change) for name, change in ABLATIONS.items()})
    points = [{'name': f'stationary-L{limit}', 'latencyLimitMs': limit, 'effects': [],
               'policies': {'oracle': {'type': 'schedule', 'default': NORMAL_ROUTE}}} for limit in (8000, 10000, 12000)]
    for limit in (8000, 10000, 12000):
        for delay in (1000, 2000, 3000):
            for duration in (12, 24, 30, 36):
                first, last = SA_FIRST, SA_FIRST+duration-1
                points.append({'name': f'L{limit}-d{delay}-n{duration}', 'latencyLimitMs': limit,
                               'effects': [mcp_delay(first, last, delay)],
                               'policies': {'oracle': oracle(first, last, dict.fromkeys(BINS, INLINE))}})
    return {'schemaVersion': 1, 'seeds': [201, 202, 203], 'replicates': 10, 'configurations': [INLINE, MCP],
            'base': {}, 'policies': policies, 'points': points}


def opposing_grid():
    policies = {'inline': {'type': 'fixed', 'configuration': INLINE}, 'mcp': {'type': 'fixed', 'configuration': MCP},
                'frozen': FROZEN, 'v1': V1, 'v2': V2}
    points = []
    for quota in (30000, 60000, 120000, 250000):
        points.append({'name': f'L{SA_LIMIT_MS}-q{quota//1000}k', 'latencyLimitMs': SA_LIMIT_MS,
            'effects': [mcp_delay(25, 48), {'kind': 'token-quota', 'tokensPerMinute': quota,
                                             'firstRequest': 49, 'lastRequest': 72}],
            'policies': {'oracle': {'type': 'schedule', 'default': NORMAL_ROUTE, 'phases': [
                {'firstRequest': 25, 'lastRequest': 48, 'configurationBySize': dict.fromkeys(BINS, INLINE)},
                {'firstRequest': 49, 'lastRequest': 72, 'configurationBySize': dict.fromkeys(BINS, MCP)}]}}})
    return {'schemaVersion': 1, 'seeds': [201, 202, 203], 'replicates': 10, 'configurations': [INLINE, MCP],
            'base': {}, 'policies': policies, 'points': points}


def transport_grid():
    policies = {'mcp': {'type': 'fixed', 'configuration': MCP}, 'function': {'type': 'fixed', 'configuration': FN},
                'frozen': FROZEN, 'v2': V2,
                'cascade': {'type': 'cascade', 'primary': MCP, 'fallbacks': [FN],
                            'triggerFailureClasses': ['step-limit', 'tool-use', 'transport']}}
    points = [{'name': f'fault{int(rate*100)}', 'latencyLimitMs': SA_LIMIT_MS,
               'effects': [{'kind': 'fault', 'configuration': MCP, 'toolErrorRate': rate, 'seed': 11,
                            'firstRequest': SA_FIRST, 'lastRequest': SA_LAST}],
               'policies': {'oracle': oracle(SA_FIRST, SA_LAST, dict.fromkeys(BINS, FN), dict.fromkeys(BINS, MCP))}}
              for rate in (0.3, 0.5, 0.7)]
    return {'schemaVersion': 1, 'seeds': [201, 202, 203], 'replicates': 10, 'configurations': [MCP, FN],
            'base': {}, 'policies': policies, 'points': points}


def cascade_policies():
    return {'inline': {'type': 'fixed', 'configuration': INLINE},
            'mcp-default': {'type': 'fixed', 'configuration': MCP},
            'mcp-lean': {'type': 'fixed', 'configuration': MCP_LEAN},
            'function-default': {'type': 'fixed', 'configuration': FN},
            'function-lean': {'type': 'fixed', 'configuration': FN_LEAN},
            'cascade-mcp': {'type': 'cascade', 'primary': MCP_LEAN, 'fallbacks': [MCP]},
            'cascade-mcp-inline': {'type': 'cascade', 'primary': MCP_LEAN, 'fallbacks': [INLINE]},
            'cascade-fn': {'type': 'cascade', 'primary': FN_LEAN, 'fallbacks': [FN]}}


def study_cascade():
    return {'schemaVersion': 1, 'baseline': BASELINE, 'configurations': [INLINE, MCP, MCP_LEAN, FN, FN_LEAN],
            'seeds': [301, 302, 303], 'repeats': 1, 'policies': cascade_policies(),
            'scenarios': {'stationary': []},
            'comparisons': [['cascade-mcp', 'mcp-default'], ['cascade-mcp', 'mcp-lean'], ['cascade-mcp', 'inline'],
                            ['cascade-mcp-inline', 'inline'], ['cascade-fn', 'function-default'],
                            ['mcp-lean', 'function-lean']]}


def study_degradation():
    return {'schemaVersion': 1, 'baseline': BASELINE, 'configurations': [INLINE, MCP],
            'seeds': [301, 302, 303], 'repeats': 1, 'latencyLimitMs': SA_LIMIT_MS,
            'policies': {'inline': {'type': 'fixed', 'configuration': INLINE},
                         'mcp': {'type': 'fixed', 'configuration': MCP},
                         'frozen': FROZEN, 'v1': V1, 'v2': V2,
                         'oracle': oracle(SA_FIRST, SA_LAST, dict.fromkeys(BINS, INLINE))},
            'scenarios': {'stationary': [], 'mcp-degraded': [mcp_delay(SA_FIRST, SA_LAST)]},
            'comparisons': [['v2', 'frozen'], ['v2', 'v1'], ['v2', 'inline'], ['v2', 'oracle'], ['v1', 'frozen']]}


PILOT_DEGRADATION_TARGETS = ['java_002', 'java_003', 'py_002', 'py_003', 'rs_001', 'rs_002', 'ts_003', 'ts_004']


def pilot_cascade():
    policies = cascade_policies()
    return {'schemaVersion': 1, 'baseline': BASELINE, 'configurations': [INLINE, MCP, MCP_LEAN, FN, FN_LEAN],
            'targets': ['rs_004', 'py_005', 'java_002', 'ts_001'], 'seeds': [901], 'repeats': 1,
            'policies': {k: policies[k] for k in ('mcp-lean', 'mcp-default', 'function-lean', 'cascade-mcp')},
            'scenarios': {'stationary': []}, 'comparisons': [['cascade-mcp', 'mcp-default']]}


def pilot_degradation():
    return {'schemaVersion': 1, 'baseline': BASELINE, 'configurations': [INLINE, MCP],
            'targets': PILOT_DEGRADATION_TARGETS, 'seeds': [902], 'repeats': 1, 'latencyLimitMs': SA_LIMIT_MS,
            'policies': {'mcp': {'type': 'fixed', 'configuration': MCP}, 'frozen': FROZEN, 'v1': V1, 'v2': V2},
            'scenarios': {'mcp-degraded': [mcp_delay(17, 32)]}, 'comparisons': [['v2', 'frozen']]}


OUTPUTS = {
    'replay/degradation.grid.json': degradation_grid, 'replay/opposing.grid.json': opposing_grid,
    'replay/transport.grid.json': transport_grid,
    'study.seams-cascade.json': study_cascade, 'study.seams-degradation.json': study_degradation,
    'pilot.cascade.json': pilot_cascade, 'pilot.degradation.json': pilot_degradation,
}


def main():
    for name, build in OUTPUTS.items():
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(build(), indent=2) + '\n')
        print(path.relative_to(ROOT))


if __name__ == '__main__':
    main()
